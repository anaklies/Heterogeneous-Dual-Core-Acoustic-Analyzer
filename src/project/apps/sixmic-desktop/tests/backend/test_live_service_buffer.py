"""Live wire service snapshots must expose real, bounded raw buffer references."""
import struct
import time
from types import SimpleNamespace

import pytest

from sixmic_backend.errors import BackendError
from sixmic_backend.model.dto import ServiceResult
from sixmic_backend.protocol.messages import ServiceHeader, encode_service_snapshot
from sixmic_backend.session import _ServiceConsumer, SessionListener


def result(words):
    return ServiceResult(source_kind='test-fixture', device_id='fixture', connection_epoch=3,
        session_id='fixture-session', service_id='fft', descriptor=600000, slot=0,
        session=1, config=10, generation=3, program_version=2, source_frame=7,
        sample_index=9007199254740993, units=None, words=struct.pack('<3I', *words),
        validity={'done':True,'error':0,'headerConsistent':True,'provenanceValid':True})


def test_service_buffer_is_readable_and_expires_on_next_snapshot(device_session_factory):
    session, _ = device_session_factory()
    received = []
    class Listener(SessionListener):
        def service_result_available(self, payload):
            received.append(payload)
    session.add_listener(Listener())
    session._on_service_result(result([11, 22, 33]))
    ref = received[-1]['words']
    assert ref['handleId'].startswith('buf-')
    assert ref['elementType'] == 'uint32' and ref['count'] == 3
    assert session.read_buffer(ref['handleId'], 1, 1) == struct.pack('<I', 22)
    assert received[-1]['sampleIndex'] == '9007199254740993'
    assert received[-1]['decoded'] is None  # No guessed acoustic values/units.
    session._on_service_result(result([44, 55, 66]))
    with pytest.raises(BackendError):
        session.read_buffer(ref['handleId'], 0, 3)


def test_service_stream_roundtrip_uses_registered_words(device_session_factory):
    session, _ = device_session_factory()
    received = []
    class Listener(SessionListener):
        def service_result_available(self, payload):
            received.append(payload)
    session.add_listener(Listener())
    session.connect()
    session.subscribe(['serviceSnapshot'])
    until = time.monotonic() + 5
    while not received and time.monotonic() < until:
        time.sleep(0.02)
    assert received, 'service snapshot did not arrive through the binary protocol'
    frame = received[0]
    assert frame['sourceKind'] == 'test-fixture'
    assert frame['validity']['provenanceValid'] is True
    ref = frame['words']
    assert session.read_buffer(ref['handleId'], 0, ref['count']) == struct.pack('<3I', 0x3f800000, 0x40000000, 0)
    session.disconnect()
    with pytest.raises(BackendError):
        session.read_buffer(ref['handleId'], 0, 1)


@pytest.mark.parametrize('field,value', [('done',0),('error',5),('session',2),('config',11),('generation',4)])
def test_service_consumer_rejects_unusable_or_mismatched_publication(field, value):
    received = []
    fake_session = SimpleNamespace(session_id='fixture-session', _on_service_result=received.append)
    consumer = _ServiceConsumer(fake_session)
    kwargs = dict(commit_sequence=42, session=1, config=10, generation=3,
        program_version=2, source_frame=7, sample_index_low=1, sample_index_high=0,
        slot=0, length=3, descriptor=600000, error=0, pc=1, done=1)
    kwargs[field] = value
    payload = encode_service_snapshot(ServiceHeader(**kwargs), struct.pack('<3I', 1,2,3))
    schema = {'sourceKind':'test-fixture','deviceId':'fixture','connectionEpoch':'3',
              'serviceId':'fft','session':1,'config':10,'generation':3}
    consumer.on_schema(schema)
    with pytest.raises(BackendError):
        consumer.on_payload(SimpleNamespace(), payload, schema)
    assert received == []
