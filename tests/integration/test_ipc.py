import json
import subprocess
import sys
from uuid import uuid4


def test_worker_subprocess():
    commands = [{'version':1, 'id':str(uuid4()), 'type':'COMMAND', 'name':name, 'payload':{}}
                for name in ['PING', 'CHECK_SESSION', 'READ_REQUISITION', 'DO_NOT_EXIST', 'PING']]
    result = subprocess.run([sys.executable, '-m', 'engine.worker'],
        input='not json\n' + '\n'.join(json.dumps(c) for c in commands) + '\n',
        text=True, capture_output=True, timeout=15, check=True)
    responses = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(responses) == 6
    assert responses[0]['code'] == 'IPC_ERROR'
    assert responses[1]['payload']['read_only'] is True
    assert responses[2]['payload']['state'] == 'DISCONNECTED'
    assert responses[3]['code'] == 'REAUTH_REQUIRED'
    assert responses[4]['code'] == 'IPC_ERROR'
    assert responses[5]['id'] == commands[-1]['id']
    assert 'ERROR' in result.stderr


def test_oversized_line_terminates():
    result = subprocess.run([sys.executable, '-m', 'engine.worker'], input='x' * (1024*1024+2),
                            text=True, capture_output=True, timeout=15)
    assert json.loads(result.stdout)['code'] == 'IPC_ERROR'
