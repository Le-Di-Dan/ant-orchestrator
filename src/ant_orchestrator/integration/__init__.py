"""Phase 5 CP6 integration layer — wires the Documentation Ant into the durable workflow.

This package is the composition/integration seam: unlike the inner layers it is free
to import ``workers``, ``execution``, ``context``, ``energy`` and ``persistence`` so it
can assemble the real production path (context preparation → proposal → approval binding
→ stable attempt → ``ApprovedExecutionScope`` → ``DocumentationAnt`` → durable WorkerRun/
ExecutionEvidence persistence → journal completion → attempt settlement). The graph and
the application services stay infra-free; this layer holds the wiring they cannot.
"""
