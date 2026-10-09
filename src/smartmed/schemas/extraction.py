"""Versioned six-field contract; not the untested full SOAP schema."""

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

FIELDS = ("发热", "咳嗽", "症状持续时间", "青霉素过敏", "已用药物", "已用药物剂量")
CONTRACT_VERSION = "extraction.v1"
Text = Annotated[str, Field(min_length=1, max_length=2000)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Turn(StrictModel):
    turn_id: int = Field(ge=1)
    speaker: Literal["patient", "doctor"]
    text: Text

    @model_validator(mode="after")
    def nonblank(self):
        if not self.text.strip():
            raise ValueError("发言不能为空")
        return self


class ExtractRequest(StrictModel):
    turns: list[Turn] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def input_bounds(self):
        ids = [turn.turn_id for turn in self.turns]
        if len(ids) != len(set(ids)):
            raise ValueError("turn_id必须唯一")
        if sum(len(turn.text) for turn in self.turns) > 2000:
            raise ValueError("本原型每次最多接收2000个字符；请勿静默截断对话")
        return self


class Evidence(StrictModel):
    turn_id: int = Field(ge=1)
    quote: Text


class PresentFact(StrictModel):
    status: Literal["present"]
    value: Text
    evidence: list[Evidence] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def nonblank(self):
        if not self.value.strip():
            raise ValueError("present必须有非空value")
        return self


class NegatedFact(StrictModel):
    status: Literal["negated"]
    value: None
    evidence: list[Evidence] = Field(min_length=1, max_length=8)


class UnknownFact(StrictModel):
    status: Literal["unknown"]
    value: None
    evidence: list[Evidence] = Field(max_length=0)


# State-dependent restrictions are in JSON Schema too, not only Python validators.
# Ollama can constrain each alternative during generation.
Fact = PresentFact | NegatedFact | UnknownFact


class Extraction(StrictModel):
    发热: Fact
    咳嗽: Fact
    症状持续时间: Fact
    青霉素过敏: Fact
    已用药物: Fact
    已用药物剂量: Fact

    @model_validator(mode="after")
    def grounding(self, info: ValidationInfo):
        # Context is supplied both by Instructor and by the manual-edit API.
        # Deserializing a stored draft alone does not repeat transcript validation.
        if not info.context or "turns" not in info.context:
            return self
        by_id = {turn.turn_id: turn for turn in info.context["turns"]}
        errors = []
        for name in FIELDS:
            fact = getattr(self, name)
            for evidence in fact.evidence:
                turn = by_id.get(evidence.turn_id)
                if (
                    turn is None
                    or turn.speaker != "patient"
                    or not evidence.quote.strip()
                    or evidence.quote not in turn.text
                ):
                    errors.append(f"{name}: 证据必须是指定患者发言的连续原文")
            if fact.status == "present" and not any(
                fact.value in evidence.quote for evidence in fact.evidence
            ):
                errors.append(f"{name}: value必须逐字复制证据中的片段")

            # Deliberately narrow guards, not a general medical fact checker.
            if name == "咳嗽" and fact.status == "present":
                if not re.search(r"咳|咯", fact.value):
                    errors.append("咳嗽: value必须描述咳嗽，不能只写持续时间")
            if name == "青霉素过敏" and fact.status == "negated":
                explicit = any(
                    re.search(
                        r"(?:对)?青霉素(?:不过敏|没有过敏|无过敏)|"
                        r"(?:没有|无|否认)青霉素过敏",
                        evidence.quote,
                    )
                    for evidence in fact.evidence
                )
                if not explicit:
                    ordered = list(info.context["turns"])
                    for evidence in fact.evidence:
                        for index, turn in enumerate(ordered):
                            if turn.turn_id != evidence.turn_id or index == 0:
                                continue
                            previous = ordered[index - 1]
                            if (
                                previous.speaker == "doctor"
                                and re.search(r"青霉素.{0,8}过敏", previous.text)
                                and not re.search(r"和|或|、|以及|布洛芬|其他药", previous.text)
                                and re.fullmatch(
                                    r"(?:我)?(?:不|没有|没|无)过敏[。！!，,]?",
                                    evidence.quote.strip(),
                                )
                            ):
                                explicit = True
                if not explicit:
                    errors.append(
                        "青霉素过敏: negated需要明确否认青霉素过敏的患者原话或紧邻提问的简短回答；"
                        "不知道、没用过、家属过敏均不能证明患者没有过敏"
                    )
            if name == "已用药物" and fact.status == "negated":
                if not any(
                    re.search(r"(?:没有|没|未|不曾)(?:吃|服用|服|使用|用)(?:过)?"
                              r"(?:任何|什么)?(?:药|药物)", evidence.quote)
                    for evidence in fact.evidence
                ):
                    errors.append(
                        "已用药物: negated需要明确否认用药的患者原话；"
                        "没有发热、不知道过敏或未提及用药不能证明没有用药"
                    )
        if errors:
            raise ValueError("; ".join(errors))
        return self


def validate_extraction(payload: dict, turns: list[Turn]) -> Extraction:
    return Extraction.model_validate(payload, context={"turns": turns})
