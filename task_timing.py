"""Adaptive post-observation pacing, with no input and no stale-frame reuse."""
import time

OBSERVATION_INTERVAL = .25

class ObservationCycle:
    """Budget one fresh capture/recognition cycle; never queue catch-up inputs."""
    def __init__(self, clock=None):
        self.clock = clock or time.monotonic
        self.begin()

    def begin(self):
        self.started = self.clock()

    def wait(self, control):
        remaining = OBSERVATION_INTERVAL - (self.clock() - self.started)
        if remaining > 0:
            control.sleep(remaining)

INTERRUPTS={'capacity_stop','resource_stop','unknown_dialog','defeat','network_error'}
STABILITY_FALLBACK_SCENES=frozenset({'unknown','unknown_dialog','loading','result_transition'})

def needs_stability_wait(scene, *, victory_verified=False):
    """Observe uncertain pages; never gate known controls on full-screen motion.

    The classifier and Runner still verify each page, current control and its
    business guards. A recognized settlement, team or free overlay can contain
    permanent character/loot animation and incidental OCR changes. Only the
    uncertain fallback waits for the whole image; resources/defeat are handled
    immediately. Weak victory text still needs observation until the complete
    result-only objectives proof is present. This policy never authorizes input.
    """
    return scene in STABILITY_FALLBACK_SCENES or (scene=='victory' and not victory_verified)

class ScreenStabilityGate:
    """Wait for consecutive stable observations; movement has no time limit.

    Compare against the last changed frame (not just adjacent frames), so slow
    fades/pans accumulate. Text/control movement also resets the quiet period.
    Small decoration flicker is tolerated; this gate never authorizes input.
    """
    def __init__(self,clock=None):
        self.clock=clock or time.monotonic;self.reset()
    def reset(self):self.since=None;self.scene=None;self.image=None;self.words=()
    def waiting(self,scene,image,words=(),width=1600,height=900):
        import cv2,numpy as np
        small=cv2.resize(np.asarray(image),(160,90)).astype(np.float32)
        labels=sorted((w['text'].strip(),w['x']/width,w['y']/height)
                      for w in words if w.get('score') is None or w['score']>=.8)
        changed=self.scene!=scene or self.image is None or len(labels)!=len(self.words)
        if not changed:
            changed=any(a[0]!=b[0] or abs(a[1]-b[1])>.008 or abs(a[2]-b[2])>.008
                        for a,b in zip(labels,self.words))
            difference=np.abs(small-self.image).mean(axis=2)
            uncertain=scene in ('unknown','unknown_dialog','loading','result_transition')
            changed=changed or float(difference.mean())>(3 if uncertain else 6) or float(np.mean(difference>24))>(.01 if uncertain else .06)
        now=self.clock()
        if changed:
            self.scene=scene;self.image=small;self.words=labels;self.since=now
            return True
        # Unknown controls must stay still before asking the user to handle them.
        return now-self.since<(4 if scene in ('unknown','unknown_dialog') else .6)

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
    # Business backoff is deliberately NOT accelerated. Ordinary delays are
    # cycle budgets, not extra sleeps after capture/OCR/persistence finishes.
    if scene in ('network_error','natural_resource_wait'):return original
    return OBSERVATION_INTERVAL
