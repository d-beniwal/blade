"""The sync <-> simulate <-> propose loop - the point of BLADE.

    real beamline  --(read-only PV reads + one frame)-->  sync      the simulator takes the real beamline's state          blade/loop/sync.py
                                                          estimate  the hidden quantities (offsets, steering ...) are fitted so that the simulator
                                                                    reproduces what was observed                           blade/loop/estimate.py
                                                          optimize  a procedure runs on a COPY of the simulator; the control changes it makes
                                                                    are the PROPOSAL                                       blade/loop/optimize.py
    a human (or, one day, an explicitly authorised actuator) applies the proposal; BLADE reads the result and goes round again     blade/loop/run.py
Applying a proposal to a read-only instrument raises ReadOnlyError: BLADE does not command the real beamline (user decision 2026-11-15). The loop is validated
end to end on a stand-in 'real' beamline that is itself a simulator with a different hidden truth (tests/test_loop.py)."""
