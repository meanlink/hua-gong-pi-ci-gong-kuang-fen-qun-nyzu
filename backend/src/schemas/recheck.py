from pydantic import BaseModel, Field
class RecheckInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    job_id: int
    error_pct: float = Field(gt=0, le=25)
    trials: int = Field(ge=5, le=100)
