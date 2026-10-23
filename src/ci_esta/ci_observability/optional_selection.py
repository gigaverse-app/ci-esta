"""Load Python report enrichment only when a report actually contains it."""
from pydantic import BaseModel


def validate_legacy_section(field: str, value):
    try:
        from ci_esta.ci_observability import python_selection_models
    except ModuleNotFoundError as error:
        if error.name and error.name.split(".")[0] == "pytest_selective":
            # Offline readers retain the original evidence even without its optional renderer.
            return value.model_dump(mode="json") if isinstance(value, BaseModel) else value
        raise
    model = (python_selection_models.SelectionSectionV1 if field == "test_selection"
             else python_selection_models.LaneSelectionSectionV1)
    return model.model_validate(value)


def badges(section, *, lanes=False):
    if isinstance(section, dict):
        return []
    from ci_esta.ci_observability import lanes as lane_renderer
    from ci_esta.ci_observability import selection
    return (lane_renderer if lanes else selection).badges(section)


def render(section, repository: str, *, lanes=False) -> str:
    if isinstance(section, dict):
        return "Python selection details are preserved in JSON. Install `ci-esta[selection]` to render them.\n"
    from ci_esta.ci_observability import lanes as lane_renderer
    from ci_esta.ci_observability import selection
    return (lane_renderer.render_lane_section(section, repository) if lanes
            else selection.render_selection_section(section, repository))
