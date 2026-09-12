from pydantic import BaseModel, ConfigDict, Field


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=2000)
    document_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{24}$")


class Evidence(BaseModel):
    source_id: str
    quote: str = Field(min_length=20, max_length=1200)


class GeneratedAnswer(BaseModel):
    answer: str = Field(min_length=1, max_length=6000)
    abstained: bool
    evidence: list[Evidence] = Field(max_length=8)


class Citation(BaseModel):
    source_id: str
    document_id: str
    filename: str
    page: int
    excerpt: str
    url: str


class Answer(BaseModel):
    answer: str
    abstained: bool
    citations: list[Citation]
    data_mode: str = "document_qa"


class KnowledgeUnavailable(Exception):
    pass


class DocumentReviewRequired(ValueError):
    pass
