#!/usr/bin/env python3
"""Real isolated mutation experiments for launch safeguards; never release approval."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parent.parent
CASES=[
 ('installer-parent-traversal', 'tools/install_local.py', 'if ".." in path.parts or not path.is_absolute()', 'if not path.is_absolute()', 'test_custom_bin_dir_parent_traversal_refused'),
 ('metadata-enum', 'hooks/capture_failure.py', 'if isinstance(event.get("tool_name"), str) and event["tool_name"] in TOOLS:', 'if isinstance(event.get("tool_name"), str):', 'test_untrusted_enum_fields_and_bool'),
 ('private-log-hardlinks', 'hooks/capture_failure.py', 'or st.st_nlink != 1', 'or False', 'test_hardlink_log_refused'),
 ('installer-apply-consent', 'tools/install_local.py', 'if not args.apply:', 'if False:', 'test_install_default_has_no_effect'),
 ('trust-record-injection', 'init-project.sh', 'if any(c in sys.argv[2] for c in "\\r\\n") or sys.argv[2] != sys.argv[2].strip():', 'if False:', 'test_trust_rejects_newline_path_injection'),
]

def test(tree,name):
    p=subprocess.run([sys.executable,'-B','-m','unittest','test_launch_safety.LaunchSafety.'+name,'-v'],cwd=tree/'tests',capture_output=True,text=True,timeout=60)
    return p.returncode,p.stdout+p.stderr

results=[]
for name,file,before,after,method in CASES:
    baseline,baseline_log=test(ROOT,method)
    if baseline: raise SystemExit('Baseline failed: '+baseline_log)
    with tempfile.TemporaryDirectory(prefix='coverloop-guardbreak-') as td:
        tree=Path(td)/'engine'
        shutil.copytree(ROOT,tree,ignore=shutil.ignore_patterns('.git','__pycache__','.coverloop'))
        p=tree/file;text=p.read_text()
        if text.count(before)!=1: raise SystemExit('Mutation target not unique: '+name)
        p.write_text(text.replace(before,after))
        code,log=test(tree,method)
        caught=code==1 and ('FAIL:' in log or 'ERROR:' in log)
        results.append({'guard':name,'baseline_exit':baseline,'mutant_exit':code,'caught':caught,'test':method,'transcript':log})
print(json.dumps({'kind':'actual isolated guard-break experiments; not a release approval','results':results},indent=2))
sys.exit(0 if all(r['caught'] for r in results) else 1)
