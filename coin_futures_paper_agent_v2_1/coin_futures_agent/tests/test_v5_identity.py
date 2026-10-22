import os
from fastapi.testclient import TestClient
from app import version


def test_probe_has_no_db_init_jobs_or_admin_access(monkeypatch):
    from app import main
    monkeypatch.setenv('AGENT_HEALTH_PROBE_ONLY','1');monkeypatch.setenv('AGENT_RELEASE_SHA','a'*40)
    def forbidden(*a,**k):raise AssertionError('No DB init or scheduler in update probe')
    monkeypatch.setattr(main,'init_db',forbidden);monkeypatch.setattr(main.scheduler,'start',forbidden)
    with TestClient(main.app) as client:
        data=client.get('/version').json()
        assert data['version']==version.VERSION and data['sha']=='a'*40 and not data['real_orders_enabled']
        assert client.get('/local/health').json()['pid']==os.getpid()
        for method,path in [('get','/api/dashboard'),('get','/health'),('post','/scan/run'),('post','/reports/recover/yesterday')]:
            assert getattr(client,method)(path).status_code==503


def test_unknown_revision_not_reported_as_official(tmp_path,monkeypatch):
    monkeypatch.setattr(version,'APP_ROOT',tmp_path);monkeypatch.setenv('AGENT_RELEASE_SHA','not-a-revision-do-not-echo')
    result=version.version_info()
    assert result['sha'] is None and result['release_status']=='ACCEPTANCE_PENDING'
    assert 'not-a-revision' not in str(result)
    (tmp_path/'.build-info.json').write_text('[]')
    assert version.version_info()['sha'] is None
