"""Synthetic, offline launch regressions. Never use the operator's HOME or keys."""
import concurrent.futures
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('capture', ROOT / 'hooks/capture_failure.py')
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


class LaunchSafety(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.home = self.root / 'home'; self.home.mkdir(mode=0o700)
        self.repo = self.root / 'repo'; self.repo.mkdir()
        self.env = {'HOME': str(self.home), 'PATH': os.environ['PATH'], 'PYTHONDONTWRITEBYTECODE': '1',
                    'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1',
                    'XDG_CONFIG_HOME': str(self.home / '.config')}
        self.run_cmd(['git', 'init', '-q', '-b', 'main'])
        self.namespace = hashlib.sha256(os.fsencode(str(self.repo))).hexdigest()[:24]
        self.folder = self.home / '.claude/coverloop-failures'
        self.log = self.folder / (self.namespace + '.jsonl')

    def tearDown(self):
        self.tmp.cleanup()

    def run_cmd(self, args, data=None, cwd=None):
        return subprocess.run([str(x) for x in args], cwd=cwd or self.repo, env=self.env,
                              input=data, capture_output=True, text=True, timeout=20)

    def hook(self, data='{}', cwd=None):
        return self.run_cmd(['bash', ROOT / 'hooks/capture-failure.sh'], data, cwd)

    def install(self, *args):
        return self.run_cmd(['bash', ROOT / 'install.sh', *args])

    def test_no_raw_content_or_supplied_path(self):
        secret = 'SYNTHETIC-PRIVATE-MARKER-78'
        payload = {'tool_name': 'Bash', 'hook_event_name': 'PostToolUseFailure', 'exit_code': 9,
                   'tool_input': {'command': secret}, 'error': secret, 'cwd': secret, 'output': secret}
        self.assertEqual(self.hook(json.dumps(payload)).returncode, 0)
        text = self.log.read_text(); self.assertNotIn(secret, text)
        rec = json.loads(text); self.assertEqual(rec['exit_code'], 9); self.assertEqual(rec['tool'], 'Bash')
        self.assertEqual(len(rec), 7)

    def test_untrusted_enum_fields_and_bool(self):
        rec = capture.summarize(json.dumps({'tool_name': 'SECRET', 'hook_event_name': 'SECRET', 'exit_code': True}).encode())
        self.assertEqual((rec['tool'], rec['event'], rec['exit_code']), ('other', 'unknown', None))
        self.assertNotIn('SECRET', json.dumps(rec))

    def test_invalid_and_oversized_input_bounded(self):
        for raw in (b'not-json-secret', b'\xff', b'['*2000, b'x'*(capture.MAX_INPUT+1)):
            rec = capture.summarize(raw); self.assertLess(len(json.dumps(rec)), 400)
        self.hook('x'*1000000)
        self.assertLess(self.log.stat().st_size, 400)
        self.assertEqual(json.loads(self.log.read_text())['input'], 'oversized-prefix')

    def test_private_modes(self):
        self.hook(); self.assertEqual(self.folder.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.log.stat().st_mode & 0o777, 0o600)

    def test_per_project_and_no_repo(self):
        self.hook()
        other = self.root/'other'; other.mkdir(); self.run_cmd(['git','init','-q'],cwd=other)
        self.hook(cwd=other); self.hook(cwd=self.home)
        self.assertEqual(len(list(self.folder.glob('*.jsonl'))), 2)

    def test_legacy_log_never_read_or_changed(self):
        (self.home/'.claude').mkdir(); legacy=self.home/'.claude/reflect-staging.md'
        legacy.write_text('SYNTHETIC-OLD-SECRET')
        self.hook(); self.assertNotIn('SECRET', self.log.read_text()); self.assertEqual(legacy.read_text(),'SYNTHETIC-OLD-SECRET')

    def test_rotation_discards_injected_fields(self):
        self.hook(); rec=json.loads(self.log.read_text()); poisoned=dict(rec, command='SYNTHETIC-LEAK')
        self.log.write_text((json.dumps(rec)+'\n')*400+json.dumps(poisoned)+'\n')
        self.hook(); self.assertEqual(len(self.log.read_text().splitlines()),300)
        self.assertNotIn('SYNTHETIC-LEAK', self.log.read_text())

    def test_symlink_log_refused(self):
        self.hook(); self.log.unlink(); target=self.root/'target'; target.write_text('unchanged')
        self.log.symlink_to(target); r=self.hook(); self.assertIn('not saved',r.stderr)
        self.assertEqual(target.read_text(),'unchanged')

    def test_hardlink_log_refused(self):
        self.hook(); target=self.root/'target'; os.link(self.log,target); before=target.read_bytes()
        self.assertIn('not saved',self.hook().stderr); self.assertEqual(target.read_bytes(),before)

    def test_fifo_log_refused_without_hang(self):
        self.hook(); self.log.unlink(); os.mkfifo(self.log,0o600)
        self.assertIn('not saved',self.hook().stderr)

    def test_directory_symlink_refused(self):
        target=self.root/'target'; target.mkdir(); (self.home/'.claude').symlink_to(target)
        self.assertIn('not saved',self.hook().stderr); self.assertEqual(list(target.iterdir()),[])

    def test_unsafe_permissions_refused(self):
        self.hook(); self.log.chmod(0o644); before=self.log.read_bytes()
        self.assertIn('not saved',self.hook().stderr); self.assertEqual(self.log.read_bytes(),before)

    def test_concurrent_log_valid_and_bounded(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(lambda _:self.hook(),range(40)))
        self.assertTrue(all(r.returncode==0 for r in results))
        rows=self.log.read_text().splitlines(); self.assertGreater(len(rows),0)
        self.assertLessEqual(len(rows),40)
        self.assertTrue(all(capture.valid(json.loads(r),capture.summarize(b'{}')) for r in rows))

    def test_install_default_has_no_effect(self):
        r=self.install(); self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(list(self.home.iterdir()),[])
        self.assertIn('"network_calls": 0',r.stdout)

    def test_clean_install_and_idempotence(self):
        r=self.install('--apply'); self.assertEqual(r.returncode,0,r.stderr)
        self.assertTrue((self.home/'bin/coverloop').exists())
        self.assertTrue((self.home/'.claude/hooks/capture_failure.py').exists())
        self.assertFalse((self.home/'.claude/settings.json').exists())
        self.assertFalse((self.home/'.config').exists())
        self.assertEqual(self.install('--apply').returncode,0)

    def test_custom_bin_dir_and_outside_refusal(self):
        custom=self.home/"tools/bin"
        self.assertEqual(self.install("--apply","--bin-dir",str(custom)).returncode,0)
        self.assertTrue((custom/"coverloop").exists())
        outside=self.root/"external"
        self.assertNotEqual(self.install("--apply","--bin-dir",str(outside)).returncode,0)
        self.assertFalse(outside.exists())

    def test_custom_bin_dir_parent_traversal_refused(self):
        escape=str(self.home/".."/"escaped")
        self.assertNotEqual(self.install("--apply","--bin-dir",escape).returncode,0)
        self.assertFalse((self.root/"escaped").exists())
        self.assertEqual(list(self.home.iterdir()),[])

    def test_identical_nonexecutable_file_requires_mode_repair(self):
        self.install("--apply")
        binary=self.home/"bin/coverloop";binary.chmod(0o600)
        self.assertNotEqual(self.install("--apply").returncode,0)
        r=self.install("--apply","--replace-existing");self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(binary.stat().st_mode & 0o777,0o700)

    def test_wiring_requires_flag_and_preserves_settings(self):
        folder=self.home/'.claude'; folder.mkdir(); path=folder/'settings.json'
        path.write_text('{"custom": "keep"}'); path.chmod(0o600)
        r=self.install('--apply','--wire-hooks'); self.assertNotEqual(r.returncode,0)
        self.assertEqual(json.loads(path.read_text()),{'custom':'keep'})
        r=self.install('--apply','--wire-hooks','--replace-existing'); self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(json.loads(path.read_text())['custom'],'keep')
        self.assertEqual(len(json.loads(path.read_text())['hooks']),4)
        self.assertEqual(len(list(folder.glob('settings.json.coverloop-backup-*'))),1)
        self.assertEqual(self.install('--apply','--wire-hooks').returncode,0)

    def test_installer_refuses_symlink_without_partial_writes(self):
        dest=self.root/'elsewhere'; dest.mkdir(); (self.home/'bin').symlink_to(dest)
        self.assertNotEqual(self.install('--apply').returncode,0)
        self.assertFalse((self.home/'.claude').exists()); self.assertEqual(list(dest.iterdir()),[])

    def test_invalid_settings_refused_before_any_write(self):
        folder=self.home/'.claude';folder.mkdir();(folder/'settings.json').write_text('[]')
        self.assertNotEqual(self.install('--apply','--wire-hooks').returncode,0)
        self.assertFalse((self.home/'bin').exists())

    def test_install_does_not_read_credential_fifo(self):
        folder=self.home/'.config/openrouter';folder.mkdir(parents=True);os.mkfifo(folder/'api_key',0o600)
        self.assertEqual(self.install('--apply').returncode,0)
        r=self.run_cmd([sys.executable,ROOT/'bin/coverloop','doctor','--no-credentials'])
        self.assertIn('not inspected',r.stdout)

    def test_project_scaffold_is_untrusted_and_generic(self):
        r=self.run_cmd(['bash',ROOT/'init-project.sh']);self.assertEqual(r.returncode,0,r.stderr)
        self.assertFalse((self.home/'.config/coverloop/trusted-repos').exists())
        self.assertIn('TEST_CMD="false"',(self.repo/'.claude/loop.conf').read_text())
        self.assertEqual((self.repo/'docs/REVIEW_LEDGER.md').read_bytes(),(ROOT/'docs/REVIEW_LEDGER.example.md').read_bytes())
        r=self.run_cmd(['bash',ROOT/'init-project.sh','--trust']);self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual((self.home/'.config/coverloop/trusted-repos').read_text().strip(),str(self.repo))

    def test_project_scaffold_refuses_hardlink(self):
        (self.repo/'.claude').mkdir(); target=self.root/'target';target.write_text('keep')
        os.link(target,self.repo/'.claude/.gitignore')
        self.assertNotEqual(self.run_cmd(['bash',ROOT/'init-project.sh']).returncode,0)
        self.assertEqual(target.read_text(),'keep')

    def test_subdirectory_trust_refused_before_writes(self):
        (self.repo/'.claude').mkdir()
        marker=self.root/'unreviewed-command'
        config=self.repo/'.claude/loop.conf'
        config.write_text('TEST_CMD="touch '+str(marker)+'"\n')
        before=config.read_bytes()
        child=self.repo/'child';child.mkdir()
        r=self.run_cmd(['bash',ROOT/'init-project.sh','--trust'],cwd=child)
        self.assertNotEqual(r.returncode,0)
        self.assertIn('repository root',r.stderr)
        self.assertEqual(list(child.iterdir()),[])
        self.assertFalse((self.home/'.config/coverloop/trusted-repos').exists())
        self.assertFalse(marker.exists())
        self.assertEqual(config.read_bytes(),before)
        hook=self.run_cmd(['bash',ROOT/'hooks/loop-stop-check.sh'])
        self.assertEqual(hook.returncode,0,hook.stderr)
        self.assertIn('NOT running',hook.stderr)
        self.assertFalse(marker.exists())
        scaffold=self.run_cmd(['bash',ROOT/'init-project.sh'],cwd=child)
        self.assertEqual(scaffold.returncode,0,scaffold.stderr)
        self.assertTrue((child/'.claude/loop.conf').exists())
        self.assertFalse((self.home/'.config/coverloop/trusted-repos').exists())

    def test_trust_accepts_worktree_root_and_physical_alias(self):
        r=self.run_cmd(['git','-c','user.name=Synthetic fixture',
                        '-c','user.email=fixture@example.invalid','commit','--allow-empty','-qm','Baseline'])
        self.assertEqual(r.returncode,0,r.stderr)
        tree=self.root/'worktree'
        r=self.run_cmd(['git','worktree','add','--detach',tree,'HEAD'])
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertTrue((tree/'.git').is_file())
        alias=self.root/'alias';alias.symlink_to(tree,target_is_directory=True)
        for cwd in (tree,alias):
            r=self.run_cmd(['bash',ROOT/'init-project.sh','--trust'],cwd=cwd)
            self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual((self.home/'.config/coverloop/trusted-repos').read_text().splitlines(),[str(tree)])

    def test_trust_rejects_newline_path_injection(self):
        victim=self.root/"victim"; victim.mkdir()
        weird=Path(str(self.root/"trusted")+"\n"+str(victim));weird.mkdir(parents=True)
        self.run_cmd(["git","init","-q"],cwd=weird)
        r=self.run_cmd(["bash",ROOT/"init-project.sh","--trust"],cwd=weird)
        self.assertNotEqual(r.returncode,0)
        self.assertFalse((self.home/".config/coverloop/trusted-repos").exists())

    def test_gate_init_safe_default_and_fifo(self):
        r=self.run_cmd([sys.executable,ROOT/'bin/coverloop','init']);self.assertEqual(r.returncode,0,r.stderr)
        p=self.repo/'.coverloop/config.json';self.assertEqual(json.loads(p.read_text())['test_command'],'false')
        p.unlink();os.mkfifo(p,0o600)
        self.assertNotEqual(self.run_cmd([sys.executable,ROOT/'bin/coverloop','init']).returncode,0)


if __name__=='__main__': unittest.main()
