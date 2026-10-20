"""Expose fixture test failures as GitHub annotations as well as the normal runner log."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


def main():
    with tempfile.TemporaryDirectory(prefix='agent-ci-') as directory:
        report=Path(directory)/'results.xml'
        result=subprocess.run([sys.executable,'-m','pytest','-q','--junitxml='+str(report)])
        if result.returncode and report.exists() and os.environ.get('GITHUB_ACTIONS')=='true':
            for case in ET.parse(report).getroot().iter('testcase'):
                for node in list(case.findall('failure'))+list(case.findall('error')):
                    message=(case.attrib.get('name','Test')+'\n'+(node.text or node.attrib.get('message','')))[-6000:]
                    message=message.replace('%','%25').replace('\r','%0D').replace('\n','%0A')
                    print('::error title=Regression test failure::'+message,flush=True)
        return result.returncode


if __name__=='__main__':
    raise SystemExit(main())
