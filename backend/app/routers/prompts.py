from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.services import prompt_registry

router = APIRouter(prefix="/prompts", tags=["prompts"])


class PromptUpdate(BaseModel):
    text: str


@router.get("")
def list_prompts():
    return {"prompts": prompt_registry.list_prompts(settings.picard_data_dir)}


@router.get("/{key}")
def get_prompt(key: str):
    try:
        return prompt_registry.get_prompt_full(key, settings.picard_data_dir)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown prompt key") from None


@router.put("/{key}")
def update_prompt(key: str, body: PromptUpdate):
    try:
        prompt_registry.save_prompt_override(key, body.text, settings.picard_data_dir)
        return prompt_registry.get_prompt_full(key, settings.picard_data_dir)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown prompt key") from None


@router.delete("/{key}")
def reset_prompt(key: str):
    try:
        prompt_registry.reset_prompt(key, settings.picard_data_dir)
        return prompt_registry.get_prompt_full(key, settings.picard_data_dir)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown prompt key") from None
