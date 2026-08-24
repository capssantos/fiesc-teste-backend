from fastapi import APIRouter, HTTPException

from app.schemas.fault import FaultDetailResponse, FaultItem
from app.services.fault_map import get_fault_entry, list_fault_entries


router = APIRouter(prefix="/faults", tags=["faults"])


@router.get("", response_model=list[FaultItem])
def list_faults() -> list[FaultItem]:
    return [FaultItem(**entry) for entry in list_fault_entries()]


@router.get("/{fault_name}", response_model=FaultDetailResponse)
def fault_detail(fault_name: str) -> FaultDetailResponse:
    entry = get_fault_entry(fault_name)
    if entry is None:
        raise HTTPException(status_code=404, detail="Fault not mapped.")
    return FaultDetailResponse(**entry)
