import copy
import threading
import time

from floating_controls import FloatingControls
from backend.models import DeviceFailure


class Service:
    def __init__(self):
        self.connected=True;self.state={'power':True,'temp':26}
        self.calls=[];self.called=threading.Event();self.failure=None
    def snapshot(self):return {'connected':self.connected,'state':copy.deepcopy(self.state)}
    def control(self,patch):
        values=patch.model_dump(exclude_unset=True)
        self.calls.append(values);self.called.set()
        if self.failure:raise self.failure
        self.state.update(values)


def test_rapid_temperature_changes_are_merged_into_one_device_write():
    service=Service();controls=FloatingControls(service)
    try:
        controls.adjust(1);controls.adjust(1);controls.adjust(-1)
        assert controls.snapshot()['state']['temp']==27
        assert service.called.wait(1)
        assert service.calls==[{'temp':27}]
    finally:controls.close()


def test_offline_queue_is_discarded_instead_of_replayed_after_reconnection():
    service=Service();controls=FloatingControls(service)
    try:
        controls.adjust(1);service.connected=False
        assert controls.snapshot()['connected'] is False
        time.sleep(.25);service.connected=True
        time.sleep(.1)
        assert not service.calls
    finally:controls.close()


def test_power_off_supersedes_unsent_temperature_changes():
    service=Service();controls=FloatingControls(service)
    try:
        controls.adjust(1);controls.submit({'power':False})
        assert service.called.wait(1)
        assert service.calls==[{'power':False}]
    finally:controls.close()


def test_unconfirmed_command_is_never_automatically_resent():
    service=Service();service.failure=DeviceFailure('not_confirmed','not confirmed')
    controls=FloatingControls(service)
    try:
        controls.adjust(1)
        assert service.called.wait(1)
        time.sleep(.3)
        assert service.calls==[{'temp':27}]
        assert controls.snapshot()['state']['temp']==26
    finally:controls.close()
