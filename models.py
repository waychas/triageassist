from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

Identifier = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
]
Text = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
]


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Identifier
    kind: Literal["log", "metric", "deployment"]
    service: Text
    timestamp: AwareDatetime
    detail: Text


class Incident(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Identifier
    service: Text
    summary: Text
    window_start: AwareDatetime
    window_end: AwareDatetime
    evidence: list[Evidence] = Field(max_length=100)

    @model_validator(mode="after")
    def check_window_and_ids(self) -> Self:
        if self.window_start > self.window_end:
            raise ValueError("window_start must not be after window_end")
        ids = [item.id for item in self.evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("Evidence IDs must be unique")
        return self


class Findings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suspected_root_cause: Text | None
    evidence_ids: list[Identifier] = Field(max_length=100)
    recommended_actions: list[Text] = Field(max_length=10)
    uncertainties: list[Text] = Field(max_length=10)

    @model_validator(mode="after")
    def require_citations(self) -> Self:
        if self.suspected_root_cause is not None and not self.evidence_ids:
            raise ValueError("A suspected root cause requires evidence IDs")
        return self


class Runbook(BaseModel):
    source: str
    content: str


class Investigation(BaseModel):
    incident_id: Identifier
    findings: Findings
    evidence: list[Evidence]
    runbooks: list[Runbook]
