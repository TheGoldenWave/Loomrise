"""仅服务端注入的事项来源；不对模型、配置编辑器或访客开放登记工具。"""
from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING

from .contracts import ServiceCycleBinding, sha256

if TYPE_CHECKING:
    from .durable_store import SqliteStore


def cycle_config_hash(orchestration: Any, unit_skill_bindings: Any) -> str:
    return sha256(json.dumps({'orchestration': orchestration, 'unit_skill_bindings': unit_skill_bindings},
                             ensure_ascii=False, sort_keys=True, separators=(',', ':')))


class ServiceCycleAuthority:
    """由宿主显式授予固定 tenant/agent/source 的业务登记权。

    grant 以当前实例的对象身份校验；复制绑定、伪造类型或知道周期 ID 不产生授权。
    持久库保留来源和初始版本。重启后受信源可重放同一来源，不能换源清空旧事项。
    """

    def __init__(self, store: SqliteStore, *, tenant_id: str, agent_id: str, authority_id: str) -> None:
        if any(not isinstance(value, str) or not value.strip() for value in (tenant_id, agent_id, authority_id)):
            raise ValueError('cycle authority scope must be explicit')
        self.store, self.tenant_id, self.agent_id, self.authority_id = store, tenant_id, agent_id, authority_id
        self._grants: dict[object, ServiceCycleBinding] = {}

    def register(self, *, subject_id: str, matter_ref: str, source_event_id: str,
                 agent_version: str, config_hash: str) -> object:
        binding = self.store.register_service_cycle(
            tenant_id=self.tenant_id, agent_id=self.agent_id, authority_id=self.authority_id,
            subject_id=subject_id, matter_ref=matter_ref, source_event_id=source_event_id,
            agent_version=agent_version, config_hash=config_hash)
        grant = object()
        self._grants[grant] = binding
        return grant

    def resolve(self, grant: object) -> ServiceCycleBinding:
        try:
            return self._grants[grant]
        except (KeyError, TypeError):
            raise ValueError('cycle grant 未由当前服务端授权器签发') from None

    def close(self, grant: object, *, reason: str = 'completed') -> dict:
        """关闭 grant 绑定的业务周期。

        关闭/撤销是终态：旧周期不能被新来源静默复用，也不能再次关闭。
        grant 仍按对象身份校验，复制绑定或知道 cycle_id 都不产生关闭权。
        """
        binding = self.resolve(grant)
        if reason not in ('completed', 'cancelled'):
            raise ValueError('cycle close reason must be completed or cancelled')
        return self.store.close_service_cycle(binding, authority_id=self.authority_id, reason=reason)

    def adjudicate(self, grant: object, *, source_event_id: str) -> object:
        """显式裁定同 subject/matter 的新业务周期（新 generation）。

        旧周期必须已 completed 关闭；新周期沿用被冻结的 agent_version/config_hash，
        并登记新的受信 source_event_id。返回绑定新周期的 grant，旧 grant 不能复用。
        """
        binding = self.resolve(grant)
        new_binding = self.store.adjudicate_new_service_cycle(
            binding, authority_id=self.authority_id, source_event_id=source_event_id)
        new_grant = object()
        self._grants[new_grant] = new_binding
        return new_grant

    def migrate(self, source_grant: object, target_grant: object, *, task_id: str) -> dict:
        """显式授权把未完成事项从已关闭源周期迁移到直系新周期。

        必须同时持有源周期与目标周期两个对象身份 grant；服务端据此校验 lineage，
        已撤销/取消或已迁移的事项不会被自动合并或复活。
        """
        source = self.resolve(source_grant)
        target = self.resolve(target_grant)
        return self.store.migrate_task_item(
            task_id=task_id, source_binding=source, target_binding=target,
            authority_id=self.authority_id)
