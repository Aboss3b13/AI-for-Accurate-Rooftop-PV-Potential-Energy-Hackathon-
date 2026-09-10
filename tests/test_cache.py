from PIL import Image
from backend.main import analyse
from backend.schemas.analysis import AnalysisSettings
from backend.services.yolo_service import yolo


def test_cached_warnings_do_not_accumulate(monkeypatch):
    cached = ['PV-only coverage']
    monkeypatch.setattr(yolo, 'detect', lambda image: ([], cached, {'available': True}))
    config = AnalysisSettings(roof=[(0,0),(100,0),(100,100),(0,100)])
    first = analyse(Image.new('RGB',(100,100)), config)
    second = analyse(Image.new('RGB',(100,100)), config)
    assert first['warnings'] == second['warnings']
    assert cached == ['PV-only coverage']
