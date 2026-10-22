"""Background screenshot-to-new-record pipeline; no Tk calls in this module."""
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event

from ocr_core import extract_document
from rda_mapping import map_rda_document
from frappe_client import FrappeError, SaveOutcomeUnknown, VerificationError


@dataclass
class CaptureJob:
    job_id: int
    path: Path
    language: str
    auto_send: bool
    cancelled: Event = field(default_factory=Event, repr=False)


@dataclass(frozen=True)
class WorkflowEvent:
    job_id: int
    phase: str
    data: object = None


def send_reviewed_job(job, payload, client, emit):
    if job.cancelled.is_set():
        return
    try:
        emit(WorkflowEvent(job.job_id, 'sending'))
        if job.cancelled.is_set():
            return
        saved = client.create_and_verify(payload, cancelled=job.cancelled)
        if not job.cancelled.is_set():
            emit(WorkflowEvent(job.job_id, 'verified', saved))
    except SaveOutcomeUnknown as error:
        emit(WorkflowEvent(job.job_id, 'outcome_unknown', error))
    except VerificationError as error:
        emit(WorkflowEvent(job.job_id, 'verification_failed', error))
    except FrappeError as error:
        emit(WorkflowEvent(job.job_id, 'failed', error))
    except Exception:
        emit(WorkflowEvent(job.job_id, 'outcome_unknown', SaveOutcomeUnknown('The save could not be confirmed. Check the site before another explicit send.')))


def run_capture_job(job, tool, client, emit):
    if job.cancelled.is_set():
        return
    try:
        document = extract_document(job.path, job.language, tool=tool)
        if job.cancelled.is_set():
            return
        emit(WorkflowEvent(job.job_id, 'ocr', document.text))
        mapping = map_rda_document(document)
        emit(WorkflowEvent(job.job_id, 'mapped', mapping))
        if job.cancelled.is_set():
            return
        if not job.auto_send or client is None:
            emit(WorkflowEvent(job.job_id, 'review_required', mapping))
        else:
            send_reviewed_job(job, mapping.payload, client, emit)
    except Exception:
        # Do not forward arbitrary exception strings, which can contain transport details.
        emit(WorkflowEvent(job.job_id, 'failed', FrappeError('Could not extract or map this capture. Retake a clear image with section labels.')))
