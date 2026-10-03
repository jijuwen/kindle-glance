"""Present a Kindle framebuffer upright for the selected physical screen direction."""
from io import BytesIO

from fastapi.responses import FileResponse, Response
from PIL import Image


def preview_response(path, rotation=0, upright=False):
    headers = {"Cache-Control": "no-store"}
    if not upright or rotation not in (90, 270):
        return FileResponse(path, media_type="image/png", headers=headers)
    # Undo only the transport rotation. Preserve its pixels, padding and render mode.
    transpose = Image.Transpose.ROTATE_90 if rotation == 90 else Image.Transpose.ROTATE_270
    with Image.open(path) as image, image.transpose(transpose) as readable:
        output = BytesIO()
        readable.save(output, "PNG")
    return Response(output.getvalue(), media_type="image/png", headers=headers)
