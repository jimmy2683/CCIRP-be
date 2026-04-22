from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class StaticGroupCreate(BaseModel):
    name: str = Field(..., min_length=1, description="Static group name")
    description: Optional[str] = None
    recipient_ids: List[str] = Field(default_factory=list)
    import_group_ids: List[str] = Field(default_factory=list)


class StaticGroupUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1)
    description: Optional[str] = None
    recipient_ids: Optional[List[str]] = None
    import_group_ids: Optional[List[str]] = None


class StaticGroupResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    type: str = "static"
    recipient_ids: List[str]
    recipient_emails: List[str]
    recipient_count: int
    created_by: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class StaticGroupCsvImportResponse(BaseModel):
    matched_recipient_ids: List[str] = Field(default_factory=list)
    matched_recipient_emails: List[str] = Field(default_factory=list)
    matched_count: int = 0
    skipped_count: int = 0
    unmatched_rows: List[str] = Field(default_factory=list)


class DynamicGroupPreferenceUpsert(BaseModel):
    tag: str = Field(..., min_length=1)
    top_k: int = Field(..., gt=0, le=10000)
    min_interactions: int = Field(default=1, ge=1)


class DynamicGroupPreferenceResponse(BaseModel):
    id: str
    tag: str
    tag_key: str
    top_k: int
    min_interactions: int
    created_by: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DynamicGroupResolveRequest(BaseModel):
    tag: str = Field(..., min_length=1)
    top_k: Optional[int] = Field(default=None, gt=0, le=10000)
    min_interactions: Optional[int] = Field(default=None, ge=1)


class DynamicGroupResolvedRecipient(BaseModel):
    id: str
    email: str
    name: str
    dynamic_score: float
    tag_score: float
    interaction_count: int
    delivery_count: int = 0
    campaign_touchpoints: int = 0
    unique_open_count: int
    unique_click_count: int
    last_open_at: Optional[datetime] = None
    last_click_at: Optional[datetime] = None


class DynamicGroupResolvedAudience(BaseModel):
    tag: str
    tag_key: str
    top_k: int
    min_interactions: int
    used_saved_top_k: bool = False
    total_eligible: int = 0
    recipients: List[DynamicGroupResolvedRecipient] = Field(default_factory=list)


class DynamicGroupResolvePayload(BaseModel):
    groups: List[DynamicGroupResolveRequest] = Field(default_factory=list)


class DynamicGroupResolveResponse(BaseModel):
    groups: List[DynamicGroupResolvedAudience] = Field(default_factory=list)


class SegmentationRequest(BaseModel):
    tag: str = Field(..., min_length=1)
    max_output_size: int = Field(default=100, gt=0, le=10000)
    similarity_threshold: float = Field(default=0.15, ge=-1.0, le=1.0)
    aggregation: Literal["max", "average"] = "max"
    weighting: Literal["proportional", "softmax"] = "proportional"
    softmax_temperature: float = Field(default=0.2, gt=0.0)


class SegmentationContribution(BaseModel):
    group_id: str
    tag: str
    tag_key: str
    similarity_score: float
    normalized_score: float
    weight: float
    requested_count: int
    selected_count: int


class SegmentationRecipient(DynamicGroupResolvedRecipient):
    source_group_ids: List[str] = Field(default_factory=list)
    source_group_tags: List[str] = Field(default_factory=list)


class SegmentationResponse(BaseModel):
    id: Optional[str] = None
    name: str
    description: Optional[str] = None
    type: str = "ai_segmentation"
    tag: str
    tag_key: str
    recipient_ids: List[str] = Field(default_factory=list)
    recipient_emails: List[str] = Field(default_factory=list)
    recipient_count: int = 0
    total_eligible_groups: int = 0
    total_matched_groups: int = 0
    similarity_scores: Dict[str, float] = Field(default_factory=dict)
    group_contributions: List[SegmentationContribution] = Field(default_factory=list)
    recipients: List[SegmentationRecipient] = Field(default_factory=list)
