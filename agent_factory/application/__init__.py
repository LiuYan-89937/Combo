"""Application services shared by CLI, slash shell, and future APIs."""

from agent_factory.application.create_agent_service import (
    CreateAgentRequest,
    CreateAgentResult,
    CreateAgentService,
)
from agent_factory.application.approval_service import ApprovalRecord, ApprovalService
from agent_factory.application.diff_service import PackageDiff, PackageDiffEntry, DiffService
from agent_factory.application.drafts_service import (
    DraftDeleteResult,
    DraftAgentDetail,
    DraftAgentSummary,
    DraftsListResult,
    DraftsService,
)
from agent_factory.application.init_factory_service import (
    InitFactoryRequest,
    InitFactoryResult,
    InitFactoryService,
)
from agent_factory.application.run_agent_service import (
    RunAgentService,
    RunAgentServiceRequest,
    RunAgentServiceResult,
)
from agent_factory.application.registry_service import (
    RegisterAgentRequest,
    RegistryListResult,
    RegistryService,
)
from agent_factory.application.patch_plan_service import PatchChange, PatchPlan, PatchPlanService
from agent_factory.application.repair_agent_service import (
    RepairAgentRequest,
    RepairAgentResult,
    RepairAgentService,
)
from agent_factory.application.test_agent_service import (
    HarnessScenarioSummary,
    TestAgentRequest,
    TestAgentResult,
    TestAgentService,
)
from agent_factory.application.upgrade_agent_service import UpgradeAgentService, UpgradeRequest
from agent_factory.application.validate_agent_service import (
    ValidateAgentRequest,
    ValidateAgentResult,
    ValidateAgentService,
)

__all__ = [
    "CreateAgentRequest",
    "CreateAgentResult",
    "CreateAgentService",
    "ApprovalRecord",
    "ApprovalService",
    "DiffService",
    "DraftDeleteResult",
    "DraftAgentDetail",
    "DraftAgentSummary",
    "DraftsListResult",
    "DraftsService",
    "InitFactoryRequest",
    "InitFactoryResult",
    "InitFactoryService",
    "RunAgentService",
    "RunAgentServiceRequest",
    "RunAgentServiceResult",
    "RegisterAgentRequest",
    "RegistryListResult",
    "RegistryService",
    "PackageDiff",
    "PackageDiffEntry",
    "PatchChange",
    "PatchPlan",
    "PatchPlanService",
    "RepairAgentRequest",
    "RepairAgentResult",
    "RepairAgentService",
    "HarnessScenarioSummary",
    "TestAgentRequest",
    "TestAgentResult",
    "TestAgentService",
    "ValidateAgentRequest",
    "ValidateAgentResult",
    "ValidateAgentService",
    "UpgradeAgentService",
    "UpgradeRequest",
]
