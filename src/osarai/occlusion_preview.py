"""Générateur local d'aperçus visuels pleine taille et mobile (`320 px`) des masques CSS."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from osarai import ExitCode, OsaraiError
from osarai.schemas import AssetsFile, FlashcardsFile, OcclusionBox, QuizFile
from osarai.yaml_io import load_yaml

TARGET_FILL_RGBA = (245, 158, 11, 232)
TARGET_OUTLINE_RGBA = (185, 28, 28, 255)
TARGET_TEXT_RGBA = (255, 255, 255, 255)

MASK_FILL_RGBA = (100, 116, 139, 242)
MASK_OUTLINE_RGBA = (51, 65, 85, 255)
MASK_TEXT_RGBA = (255, 255, 255, 255)

MOBILE_PREVIEW_WIDTH = 320


def _load_badge_font(box_height_px: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    font_size = max(11, min(36, int(box_height_px * 0.55)))
    try:
        return ImageFont.load_default(size=font_size)
    except TypeError:  # pragma: no cover
        return ImageFont.load_default()


def _compose_on_white(img: Image.Image) -> Image.Image:
    rgba = img.convert("RGBA")
    white_bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    return Image.alpha_composite(white_bg, rgba)


def _draw_occlusion_boxes(base_img: Image.Image, boxes: list[OcclusionBox]) -> Image.Image:
    canvas = _compose_on_white(base_img)
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")
    width, height = canvas.size
    stroke_w = max(2, round(min(width, height) * 0.004))

    for box in boxes:
        x0 = round((box.x / 100.0) * width)
        y0 = round((box.y / 100.0) * height)
        x1 = max(x0 + 2, round(((box.x + box.w) / 100.0) * width))
        y1 = max(y0 + 2, round(((box.y + box.h) / 100.0) * height))

        if box.role == "target":
            fill = TARGET_FILL_RGBA
            outline = TARGET_OUTLINE_RGBA
            text_color = TARGET_TEXT_RGBA
        else:
            fill = MASK_FILL_RGBA
            outline = MASK_OUTLINE_RGBA
            text_color = MASK_TEXT_RGBA

        draw.rectangle([x0, y0, x1, y1], fill=fill, outline=outline, width=stroke_w)

        if box.badge:
            font = _load_badge_font(y1 - y0)
            bbox = draw.textbbox((0, 0), box.badge, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            tx = x0 + ((x1 - x0) - tw) / 2.0 - bbox[0]
            ty = y0 + ((y1 - y0) - th) / 2.0 - bbox[1]
            draw.text((tx, ty), box.badge, fill=text_color, font=font)

    return Image.alpha_composite(canvas, overlay).convert("RGB")


def generate_occlusion_previews(
    theme_dir: Path,
    out_dir: Path,
    item_id: str | None = None,
) -> list[Path]:
    """Génère hors Git `<item_id>--full.png` et `<item_id>--mobile-320w.png`."""
    if not theme_dir.is_dir():
        raise OsaraiError(
            f"Dossier de thème introuvable : {theme_dir}",
            ExitCode.VALIDATION_ERROR,
            details={"theme_dir": str(theme_dir)},
        )

    assets_path = theme_dir / "assets.yaml"
    try:
        assets_file = AssetsFile.model_validate(load_yaml(assets_path))
    except Exception as exc:
        if isinstance(exc, OsaraiError):
            raise
        raise OsaraiError(
            f"`assets.yaml` invalide dans {theme_dir} : {exc}",
            ExitCode.VALIDATION_ERROR,
            details={"file": str(assets_path)},
        ) from exc

    asset_map = {entry.asset_id: entry for entry in assets_file.assets}
    occluded_items: list[tuple[str, str, list[OcclusionBox]]] = []

    cards_path = theme_dir / "flashcards.yaml"
    if cards_path.is_file():
        try:
            cards_file = FlashcardsFile.model_validate(load_yaml(cards_path))
        except Exception as exc:
            if isinstance(exc, OsaraiError):
                raise
            raise OsaraiError(
                f"`flashcards.yaml` invalide dans {theme_dir} : {exc}",
                ExitCode.VALIDATION_ERROR,
                details={"file": str(cards_path)},
            ) from exc

        for card in cards_file.cards:
            if card.type == "basic" and card.asset_role == "front_occluded" and card.asset_id:
                if not card.id:
                    raise OsaraiError(
                        "Exécutez `uv run osarai assign-ids` avant `preview-occlusions`.",
                        ExitCode.VALIDATION_ERROR,
                        details={"file": str(cards_path)},
                    )
                occluded_items.append((card.id, card.asset_id, card.occlusions))

    quiz_path = theme_dir / "quiz.yaml"
    if quiz_path.is_file():
        try:
            quiz_file = QuizFile.model_validate(load_yaml(quiz_path))
        except Exception as exc:
            if isinstance(exc, OsaraiError):
                raise
            raise OsaraiError(
                f"`quiz.yaml` invalide dans {theme_dir} : {exc}",
                ExitCode.VALIDATION_ERROR,
                details={"file": str(quiz_path)},
            ) from exc

        for question in quiz_file.questions:
            if question.asset_role == "front_occluded" and question.asset_id:
                if not question.id:
                    raise OsaraiError(
                        "Exécutez `uv run osarai assign-ids` avant `preview-occlusions`.",
                        ExitCode.VALIDATION_ERROR,
                        details={"file": str(quiz_path)},
                    )
                occluded_items.append((question.id, question.asset_id, question.occlusions))

    if item_id is not None:
        base_item_id = item_id.split("#", 1)[0].strip()
        occluded_items = [it for it in occluded_items if it[0] == base_item_id]
        if not occluded_items:
            raise OsaraiError(
                f"Aucun élément occulté trouvé pour `item_id={item_id!r}` dans {theme_dir}.",
                ExitCode.VALIDATION_ERROR,
                details={"item_id": item_id, "theme_dir": str(theme_dir)},
            )

    out_dir.mkdir(parents=True, exist_ok=True)
    generated_paths: list[Path] = []

    for elem_id, asset_id, boxes in occluded_items:
        asset_entry = asset_map.get(asset_id)
        if asset_entry is None:
            raise OsaraiError(
                f"`asset_id={asset_id!r}` introuvable dans `assets.yaml` pour `{elem_id}`.",
                ExitCode.VALIDATION_ERROR,
                details={"item_id": elem_id, "asset_id": asset_id},
            )
        img_path = theme_dir / "assets" / asset_entry.filename
        if not img_path.is_file():
            raise OsaraiError(
                f"Fichier image manquant : {img_path}",
                ExitCode.VALIDATION_ERROR,
                details={"file": str(img_path)},
            )

        with Image.open(img_path) as src_img:
            rendered_full = _draw_occlusion_boxes(src_img, boxes)

        full_path = out_dir / f"{elem_id}--full.png"
        rendered_full.save(full_path, format="PNG")
        generated_paths.append(full_path)

        full_w, full_h = rendered_full.size
        mobile_h = max(1, round(full_h * (MOBILE_PREVIEW_WIDTH / full_w)))
        rendered_mobile = rendered_full.resize(
            (MOBILE_PREVIEW_WIDTH, mobile_h),
            Image.Resampling.LANCZOS,
        )
        mobile_path = out_dir / f"{elem_id}--mobile-320w.png"
        rendered_mobile.save(mobile_path, format="PNG")
        generated_paths.append(mobile_path)

    return generated_paths
