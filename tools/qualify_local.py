#!/usr/bin/env python3
"""Offline synthetic customer journey. No providers, real approvals or release attestations."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--engine-repo',default=str(Path(__file__).resolve().parent.parent))
p.add_argument('--commit',required=True)
a=p.parse_args()
records=[]
with tempfile.TemporaryDirectory(prefix='coverloop-qualification-') as td:
    root=Path(td).resolve();home=root/'home';home.mkdir(mode=0o700)
    repo=root/'project';repo.mkdir();engine=root/'engine';template=root/'empty-template';template.mkdir()
    env={'HOME':str(home),'PATH':os.environ['PATH'],'PYTHONDONTWRITEBYTECODE':'1',
         'GIT_CONFIG_GLOBAL':'/dev/null','GIT_CONFIG_NOSYSTEM':'1','GIT_TERMINAL_PROMPT':'0',
         'XDG_CONFIG_HOME':str(home/'.config')}
    def run(label,cmd,cwd=repo,expected=0):
        r=subprocess.run([str(x) for x in cmd],cwd=cwd,env=env,capture_output=True,text=True,timeout=60)
        output=(r.stdout+r.stderr).replace(str(root),'<synthetic-workspace>')
        records.append({'step':label,'exit_code':r.returncode,'expected':expected,'output':output})
        if r.returncode!=expected:
            print(json.dumps(records,indent=2));raise SystemExit('Unexpected result: '+label)
        return r.stdout
    def git(label,*args):return run(label,['git','-c','core.hooksPath=/dev/null','-c','init.templateDir='+str(template),*args])
    run('fresh offline clone',['git','-c','core.hooksPath=/dev/null','clone','--no-hardlinks','--no-checkout','--template='+str(template),Path(a.engine_repo).resolve(),engine])
    run('checkout immutable commit',['git','-c','core.hooksPath=/dev/null','checkout','--detach',a.commit],cwd=engine)
    actual=run('verify commit',['git','rev-parse','HEAD'],cwd=engine).strip()
    if actual!=a.commit:raise SystemExit('Commit mismatch')
    if run('verify clean source',['git','status','--porcelain'],cwd=engine).strip():raise SystemExit('Dirty engine')
    digest=hashlib.sha256((engine/'bin/coverloop').read_bytes()).hexdigest()
    run('installation preview',['bash',engine/'install.sh'])
    assert not list(home.iterdir()),'preview mutated HOME'
    run('approved offline install',['bash',engine/'install.sh','--apply'])
    assert not (home/'.config').exists(),'installation trusted a project or touched credentials'
    gate=[sys.executable,home/'bin/coverloop']
    inventory=subprocess.run([*map(str,gate),'doctor','--no-credentials'],cwd=repo,env=env,capture_output=True,text=True)
    assert inventory.returncode in (0,1) and 'not inspected' in inventory.stdout
    records.append({'step':'dependency inventory','exit_code':inventory.returncode,'expected':'0 or 1; missing optional tools reported','output':inventory.stdout.replace(str(root),'<synthetic-workspace>')})
    git('initialize synthetic project','init','-q','-b','main')
    git('synthetic identity','config','user.name','Synthetic fixture');git('synthetic email','config','user.email','fixture@example.invalid')
    (repo/'app.py').write_text('def normalize(text):\n    return text.strip()\n')
    (repo/'test_app.py').write_text('import unittest\nfrom app import normalize\nclass TestNormalize(unittest.TestCase):\n    def test_whitespace(self):\n        self.assertEqual(normalize("  hello  "), "hello")\n    def test_case(self):\n        self.assertEqual(normalize("HELLO"), "hello")\n')
    run('real regression fails before fix',[sys.executable,'-B','-m','unittest','-v'],expected=1)
    run('configure real tests',[*gate,'init','--test-command','python3 -B -m unittest -v'])
    scaffold=root/'scaffold-project';scaffold.mkdir()
    run('initialize scaffold fixture',['git','init','-q'],cwd=scaffold)
    run('generic project setup',['bash',engine/'init-project.sh'],cwd=scaffold)
    assert not (home/'.config/coverloop/trusted-repos').exists()
    git('commit synthetic source','add','-A');git('commit synthetic source','commit','-qm','Synthetic baseline')
    base=git('record base','rev-parse','HEAD').strip()
    (repo/'app.py').write_text('def normalize(text):\n    return text.strip().lower()\n')
    git('commit meaningful change','add','app.py');git('commit meaningful change','commit','-qm','Normalize case')
    tier=run('classify code',[*gate,'classify','--quiet','--base',base]).strip();assert tier=='L1',tier
    run('missing evidence blocks',[*gate,'gate','--min-tier','L1','--base',base,'--require-transcript'],expected=1)
    run('run actual test and attest',[*gate,'attest','--tier','L1','--tests'])
    git('commit actual evidence','add','.coverloop/reports');git('commit actual evidence','commit','-qm','Record actual synthetic test evidence')
    run('valid L1 evidence passes',[*gate,'gate','--min-tier','L1','--base',base,'--require-transcript'])
    (repo/'app.py').write_text('def normalize(text):\n    return text.strip().lower() # changed after evidence\n')
    git('change code after evidence','add','app.py');git('change code after evidence','commit','-qm','Change invalidates evidence')
    run('stale evidence blocks',[*gate,'gate','--min-tier','L1','--base',base,'--require-transcript'],expected=1)
    run('refresh actual test evidence',[*gate,'attest','--tier','L2','--tests'])
    run('actual failed reviewer process',[*gate,'attest','--codex','fail','--codex-run',"python3 -c 'raise SystemExit(7)'"],expected=1)
    run('failed reviewer blocks',[*gate,'gate','--min-tier','L2','--require-transcript'],expected=1)
    run('raise L3 without approval',[*gate,'attest','--tier','L3','--tests'],expected=1)
    output=run('missing L3 mutation and approval block',[*gate,'gate','--min-tier','L3','--require-transcript'],expected=1)
    assert 'mutation' in output and 'human' in output,output
print(json.dumps({'scope':'offline synthetic customer journey; no release approval or provider readiness claim',
                  'engine_commit':a.commit,'gate_sha256':digest,'python':sys.version.split()[0],'platform':sys.platform,'records':records},indent=2))
