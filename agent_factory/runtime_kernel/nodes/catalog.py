from __future__ import annotations

NODE_TYPES = {
    "reserved",
    "cognitive",
    "operational",
    "governance",
    "terminal",
    "sub_graph",
}

KERNEL_RESERVED_NODES = {"ingress", "finalize"}

NODE_IMPLEMENTATION_IDS = {
    "ingress",
    "finalize",
    "governance.precheck",
    "governance.postcheck",
    "governance.approval_gate",
    "governance.refusal_gate",
    "cognitive.clarify",
    "cognitive.plan",
    "cognitive.route",
    "cognitive.structured",
    "cognitive.answer",
    "cognitive.review",
    "operational.tool_call",
    "operational.resource_probe",
    "terminal.commit",
    "terminal.close",
}

INTERRUPT_CAPABLE_IMPLS = {
    "governance.precheck",
    "governance.postcheck",
    "governance.approval_gate",
    "operational.tool_call",
}

SUBGRAPH_SLOT_IMPLS = {
    "governance.precheck",
    "governance.postcheck",
    "governance.approval_gate",
    "governance.refusal_gate",
    "cognitive.clarify",
    "cognitive.plan",
    "cognitive.route",
    "cognitive.answer",
    "cognitive.review",
    "operational.tool_call",
    "operational.resource_probe",
}
