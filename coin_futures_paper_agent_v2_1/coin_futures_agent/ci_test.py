"""Expose fixture test failures as GitHub annotations as well as the normal runner log."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


def main():
    if os.environ.get('GITHUB_ACTIONS') == 'true' and hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
    with tempfile.TemporaryDirectory(prefix='agent-ci-') as directory:
        report=Path(directory)/'results.xml'
        result=subprocess.run([sys.executable,'-m','pytest','-q','--junitxml='+str(report)])
        if result.returncode and report.exists() and os.environ.get('GITHUB_ACTIONS')=='true':
            for case in ET.parse(report).getroot().iter('testcase'):
                for node in list(case.findall('failure'))+list(case.findall('error')):
                    # GitHub truncates long annotation messages before the exception
                    # when a verbose traceback includes the whole fixture body.
                    message=case.attrib.get('name','Test')+'\n'+(node.text or node.attrib.get('message',''))[-2800:]
                    message=message.replace('%','%25').replace('\r','%0D').replace('\n','%0A')
                    print('::error title=Regression test failure::'+message,flush=True)
        return result.returncode


if __name__=='__main__':
    raise SystemExit(main())
