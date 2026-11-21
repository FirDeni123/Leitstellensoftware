"""Excel/CSV import endpoints (vehicles, stations)."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from app.api.crud_router import visible_control_centers
from app.api.deps import AuthContext, UowDep, require, uow_for
from app.core.errors import PermissionDeniedError, ValidationFailedError
from app.core.permissions import P
from app.models import ImportJob
from app.schemas.imports import CommitRequest, ImportJobOut, ImportJobSummary, ImportKind, MappingRequest
from app.services.import_files import MAX_FILE_BYTES
from app.services.import_service import FIELDS, PREVIEW_ROWS, ImportService

router = APIRouter(prefix="/imports", tags=["Datenimport"])

CanImport = Annotated[AuthContext, Depends(require(P.DATA_IMPORT, P.MASTER_DATA_READ))]
TARGET_PERMISSION = {"vehicles": P.VEHICLES_WRITE, "stations": P.STATIONS_WRITE}


def _check_target(auth: AuthContext, kind: str) -> None:
    needed = TARGET_PERMISSION[kind]
    if not auth.has(needed):
        raise PermissionDeniedError(details={"missing_permissions": [needed.value]})


def job_out(job: ImportJob, sheets: list[str] | None = None) -> ImportJobOut:
    data: dict[str, Any] = {name: getattr(job, name) for name in ImportJobSummary.model_fields}
    data.update(
        headers=job.headers,
        sample_rows=(job.rows or [])[:PREVIEW_ROWS],
        sheets=sheets or [],
        fields=[
            {"key": f.key, "label": f.label, "required": f.required, "hint": f.hint} for f in FIELDS[job.kind]
        ],
        column_mapping=job.column_mapping,
        options=job.options,
        validation=job.validation,
    )
    return ImportJobOut.model_validate(data)


@router.post(
    "",
    response_model=ImportJobOut,
    status_code=status.HTTP_201_CREATED,
    summary="Datei hochladen (.xlsx/.csv) – erzeugt Vorschau und Zuordnungsvorschlag",
)
async def upload(
    auth: CanImport,
    uow: UowDep,
    file: Annotated[UploadFile, File()],
    kind: Annotated[ImportKind, Form()],
    control_center_id: Annotated[uuid.UUID, Form()],
    sheet: Annotated[str | None, Form()] = None,
) -> ImportJobOut:
    _check_target(auth, kind)
    content = await file.read(MAX_FILE_BYTES + 1)
    if len(content) > MAX_FILE_BYTES:
        raise ValidationFailedError(f"Datei zu groß (maximal {MAX_FILE_BYTES // (1024 * 1024)} MB)")
    service = ImportService(uow_for(auth, uow), visible_control_centers(auth))
    job, sheets = await service.upload(control_center_id, kind, file.filename or "import", content, sheet)
    return job_out(job, sheets)


@router.get("", response_model=list[ImportJobSummary], summary="Letzte Importe")
async def list_imports(auth: CanImport, uow: UowDep, control_center_id: uuid.UUID | None = None) -> Any:
    jobs = await ImportService(uow, visible_control_centers(auth)).list(control_center_id)
    return [ImportJobSummary.model_validate(j) for j in jobs]


@router.get("/{job_id}", response_model=ImportJobOut)
async def get_import(job_id: uuid.UUID, auth: CanImport, uow: UowDep) -> ImportJobOut:
    return job_out(await ImportService(uow, visible_control_centers(auth)).get(job_id))


@router.put(
    "/{job_id}/mapping",
    response_model=ImportJobOut,
    summary="Spaltenzuordnung festlegen und alle Zeilen prüfen (schreibt keine Stammdaten)",
)
async def set_mapping(job_id: uuid.UUID, body: MappingRequest, auth: CanImport, uow: UowDep) -> ImportJobOut:
    service = ImportService(uow_for(auth, uow), visible_control_centers(auth))
    _check_target(auth, (await service.get(job_id)).kind)
    job = await service.validate(job_id, body.mapping, body.update_existing, body.expected_version)
    return job_out(job)


@router.post(
    "/{job_id}/commit",
    response_model=ImportJobOut,
    summary="Geprüfte Daten übernehmen (eine Transaktion, jeder Datensatz protokolliert)",
)
async def commit(job_id: uuid.UUID, body: CommitRequest, auth: CanImport, uow: UowDep) -> ImportJobOut:
    service = ImportService(uow_for(auth, uow), visible_control_centers(auth))
    _check_target(auth, (await service.get(job_id)).kind)
    return job_out(await service.commit(job_id, body.expected_version, body.skip_invalid))


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Import verwerfen")
async def discard(job_id: uuid.UUID, auth: CanImport, uow: UowDep) -> None:
    await ImportService(uow_for(auth, uow), visible_control_centers(auth)).discard(job_id)
