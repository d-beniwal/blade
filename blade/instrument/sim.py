"""`SimInstrument`: the virtual beamline (blade.vbl.world.VirtualBeamline) behind the `Instrument` interface. SIMULATION ONLY - nothing here touches EPICS.

Two ways to get one:
  SimInstrument(world)                  wrap a World object (what the loop does for its model copy; no persistence)
  SimInstrument.session("default")      the shared on-disk session (runs/vbl/<name>.json) that the GUI page /vbl and the vbl_* MCP tools also use: it re-reads
                                        the file before every operation and saves after every change, so all of them see one beamline.
`truth()` returns the hidden truth report - for tests, scoring and the estimator's validation only, never for procedures."""
from ..vbl import imaging, store
from ..vbl.world import VirtualBeamline, control_specs
from .base import Instrument


class SimInstrument(Instrument):
    name = "sim"
    writable = True

    def __init__(self, world=None, seed=0, scenario="startup", session=None):
        self._session = session
        if world is None and session is not None:
            world = store.load(session) or store.reset(seed, scenario, session)
        self.world = world if world is not None else VirtualBeamline(seed=seed, scenario=scenario)
        self._bind()

    @classmethod
    def session(cls, name=store.DEFAULT, seed=0, scenario="startup"):
        return cls(None, seed, scenario, session=name)

    def _bind(self):
        w = self.world
        self.sim, self.cams, self.z = w.sim, w.cams, w.z

    def _pre(self):
        if self._session is not None:                    # the GUI / vbl_* tools may have changed the beamline since the last call
            self.world = store.load(self._session) or self.world
            self._bind()

    def _post(self):
        if self._session is not None:
            store.save(self.world, self._session)

    # -- reads ----------------------------------------------------------------------------------------------------------------
    def controls(self):
        return control_specs(self.world.twin)

    def ctl(self, name):
        self._pre()
        return self.world.ctl(name)

    def ic_kHz(self, ic):
        self._pre()
        return self.world.ic_kHz(ic)

    def mu_t(self):
        self._pre()
        return self.world.mu_t()

    def frame(self, cam, exposure=None, bin_=1):
        self._pre()
        img = imaging.render(self.world, cam, exposure=exposure, bin_=bin_)
        self._post()                                     # rendering advances the acquisition counter / texture state
        return img

    def snapshot(self):
        self._pre()
        return self.world.snapshot()

    # -- writes ---------------------------------------------------------------------------------------------------------------
    def set(self, name, value):
        self._pre()
        r = self.world.set(name, value)
        self._post()
        return r

    def assign(self, values):
        """Put control values into the model as STATE, without simulating the motion (no clock advance, no hysteresis): what `blade.loop.sync` does with values read
        from the real beamline. Unknown names and out-of-range values are skipped and reported. Returns {"assigned": [...], "skipped": {name: reason}}."""
        self._pre()
        specs, ctl, out = self.controls(), self.world.s["ctl"], {"assigned": [], "skipped": {}}
        for name, v in values.items():
            if name not in specs:
                out["skipped"][name] = "not a control of the simulator"
                continue
            lo, hi = specs[name][0], specs[name][1]
            if isinstance(ctl[name], str):
                ctl[name] = v if isinstance(v, str) else ctl[name]
            elif lo is not None and not (lo <= float(v) <= hi):
                out["skipped"][name] = f"{v} outside the simulator's limits [{lo}, {hi}]"
                continue
            else:
                ctl[name] = int(v) if isinstance(ctl[name], int) and not isinstance(ctl[name], bool) else float(v)
            out["assigned"].append(name)
        self._post()
        return out

    def wait(self, seconds):
        self._pre()
        self.world.advance(float(seconds))
        self._post()

    # -- simulator-only -------------------------------------------------------------------------------------------------------
    def truth(self):
        """The hidden truth vs the current settings (tests / scoring only)."""
        self._pre()
        return self.world.truth_report()

    def copy(self, noiseless=False):
        """An independent simulator with the same state (the loop optimises on a copy and never disturbs the original). noiseless=True: ion-chamber read-outs
        without noise (what the estimator predicts with)."""
        import copy as _copy
        self._pre()
        w = VirtualBeamline(state=_copy.deepcopy(self.world.s), twin=self.world.twin)
        if noiseless:
            w.noise_scale = 0.0
        return SimInstrument(w)
