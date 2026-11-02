"""Adaptive post-observation pacing, with no input and no stale-frame reuse."""
import time

INTERRUPTS={'capacity_stop','resource_stop','unknown_dialog','defeat','network_error'}
class TransitionPacer:
    def __init__(self,clock=time.monotonic):
        self.clock=clock;self.scene=None;self.until=0
    def applied(self,scene,entry=False):
        self.scene=scene;self.until=self.clock()+(15 if entry else 3)
    def waiting(self,scene):
        if scene in INTERRUPTS or scene!=self.scene or self.clock()>=self.until:
            self.scene=None;return False
        return True
    def reset(self):self.scene=None;self.until=0

def next_delay(scene,original,acted=False):
    # Network reconnect backoff is deliberately NOT accelerated.
    if scene=='network_error':return original
    if scene=='battle':return 2.5
    if scene in ('loading','result_transition','unknown'):return min(original,1.0)
    return min(original,.45 if acted else .7)
