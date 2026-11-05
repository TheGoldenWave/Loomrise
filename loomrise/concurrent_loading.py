"""Select optional Skill context without changing the primary request or tools."""
from collections import Counter
from collections.abc import Mapping
import inspect
from typing import Any, Callable

from .contracts import ScenarioPack
from .graph_runtime import RouteResult


def default_selector(candidates: list[dict[str, Any]], text: str, routing: Mapping[str, Any]) -> list[str]:
    """Deterministic recall provider for R3's offline/default runtime.

    It ranks only the already filtered candidate Unit IDs from routing keywords.
    It never becomes the primary route and never exposes a tool schema.
    """
    scores = []
    for candidate in candidates:
        keywords = routing.get(candidate['skill_id'], []) if isinstance(routing, Mapping) else []
        score = sum(1 for keyword in keywords if isinstance(keyword, str) and keyword and keyword in text)
        if score:
            scores.append((score, candidate['unit_id']))
    return [unit_id for _, unit_id in sorted(scores, key=lambda item: (-item[0], item[1]))]


def _visited_units(config: Mapping[str, Any], route: RouteResult) -> set[str]:
    registry = {unit['unit_id']: unit for unit in config.get('units', [])
                if isinstance(unit, Mapping) and isinstance(unit.get('unit_id'), str)}
    visited = set()
    for step in route.steps:
        if step.kind != 'enter':
            continue
        graph = config.get('orchestration', {})
        for local_id in (*step.layer, step.target.split('.')[0]):
            node = next((node for node in graph.get('nodes', []) if node.get('id') == local_id), None)
            ref = node.get('unit_ref', {}) if isinstance(node, Mapping) else {}
            unit = registry.get(ref.get('unit_id'))
            if unit is None or unit.get('version') != ref.get('version'):
                break
            visited.add(unit['unit_id'])
            graph = unit.get('body', {})
    return visited


async def select_concurrent_skills(
    config: Mapping[str, Any], pack: ScenarioPack, bindings: Mapping[str, str],
    route: RouteResult, *, text: str, available_skills: set[str],
    selector: Callable[..., Any] | None, emit: Callable[..., Any],
) -> list[str]:
    """Only registered, applicable, currently usable candidates reach the selector.

    The selector returns ranked Unit IDs; its suggestions never grant tool or
    knowledge access. The ContextLedger rechecks fragment validity and budget
    when loading the selected context. Missing providers mean no optional recall.
    """
    units = [unit for unit in config.get('units', []) if isinstance(unit, Mapping)]
    helpers = [unit for unit in units if unit.get('load_mode') == 'concurrent']
    if not helpers:
        return []
    group = config.get('concurrent_config')
    limit = group.get('max_units') if isinstance(group, Mapping) else None
    if type(limit) is not int or limit < 1:
        emit('recall.diagnostic', code='invalid_concurrent_limit', selected_count=0)
        return []
    ids = Counter(unit.get('unit_id') for unit in units if isinstance(unit.get('unit_id'), str))
    skill_counts = Counter(skill.skill_id for skill in pack.skills)
    registered = {skill.skill_id: skill for skill in pack.skills
                  if skill_counts[skill.skill_id] == 1 and skill.skill_id in pack.agent_version.skill_ids}
    visited = _visited_units(config, route)
    routed = {unit['unit_id'] for unit in units
              if isinstance(unit.get('unit_id'), str) and unit.get('load_mode') == 'routed'}
    candidates = []
    eligible = {}
    for unit in helpers:
        uid = unit.get('unit_id')
        if not isinstance(uid, str) or ids[uid] != 1 or type(unit.get('version')) is not int or unit['version'] < 1:
            continue
        skill_id = bindings.get(uid)
        skill = registered.get(skill_id)
        reason = None
        scope = unit.get('load_scope')
        if 'load_scope' in unit:
            if (not isinstance(scope, Mapping) or not scope or set(scope) - {'after', 'exclude'}
                    or ('after' in scope and (not isinstance(scope['after'], str) or scope['after'] not in routed))
                    or ('exclude' in scope and (not isinstance(scope['exclude'], list) or not scope['exclude']
                        or any(not isinstance(item, str) or item not in routed for item in scope['exclude'])))):
                reason = 'invalid_load_scope'
            elif scope.get('after') and (scope['after'] not in visited or scope['after'] == route.terminal_unit_id):
                reason = 'before_load_scope'
            elif route.terminal_unit_id in scope.get('exclude', []):
                reason = 'excluded_current_unit'
        if reason is None and (skill is None or skill_id not in available_skills):
            reason = 'unavailable_skill_context'
        if reason is not None:
            emit('recall.diagnostic', code=reason, unit_id=uid, selected_count=0)
            continue
        eligible[uid] = skill_id
        candidates.append({'unit_id': uid, 'version': unit['version'], 'skill_id': skill_id,
                           'skill_version': skill.version, 'title': skill.title, 'applies_when': skill.applies_when})
    provider = 'injected'
    if selector is None:
        provider = 'deterministic-keyword-v1'
        suggested = default_selector(candidates, text, pack.routing)
    else:
        try:
            suggested = selector(candidates, {'input': text, 'current_unit_id': route.terminal_unit_id})
            if inspect.isawaitable(suggested):
                suggested = await suggested
        except Exception:
            emit('recall.diagnostic', code='selector_failed', candidate_count=len(candidates), selected_count=0, provider=provider)
            return []
    if not candidates:
        emit('recall.diagnostic', code='no_eligible_candidates', candidate_count=0, selected_count=0)
        return []
    if not isinstance(suggested, list) or any(not isinstance(uid, str) or uid not in eligible for uid in suggested):
        emit('recall.diagnostic', code='invalid_selection', candidate_count=len(candidates), selected_count=0)
        return []
    selected, skills = [], []
    for uid in suggested:
        if uid in selected or eligible[uid] in skills:
            continue
        if len(selected) == limit:
            break
        selected.append(uid)
        skills.append(eligible[uid])
    emit('recall.diagnostic', code='selected', candidate_count=len(candidates), selected_count=len(selected),
         selected_unit_ids=selected, max_units=limit, provider=provider, diagnostic_only=True)
    return skills
