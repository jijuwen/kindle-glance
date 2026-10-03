"""Preview orientation follows the physical screen without changing transport files."""
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.responses import FileResponse
from PIL import Image

from app.preview import preview_response


class PreviewOrientationTest(unittest.TestCase):
    def test_both_landscape_rotations_restore_asymmetric_pixels(self):
        with tempfile.TemporaryDirectory() as temporary:
            native = Image.new('L', (8, 6), 255)
            native.putpixel((0, 0), 12)
            native.putpixel((7, 0), 71)
            native.putpixel((0, 5), 132)
            native.putpixel((7, 5), 191)
            for rotation, transpose in [(90,Image.Transpose.ROTATE_270),(270,Image.Transpose.ROTATE_90)]:
                with self.subTest(rotation=rotation):
                    path = Path(temporary)/f'screen-{rotation}.png'
                    native.transpose(transpose).save(path)
                    before = path.read_bytes()
                    response = preview_response(path,rotation,upright=True)
                    with Image.open(BytesIO(response.body)) as restored:
                        self.assertEqual(restored.size,(8,6))
                        self.assertEqual(restored.tobytes(),native.tobytes())
                    self.assertEqual(path.read_bytes(),before)
                    self.assertEqual(response.headers['cache-control'],'no-store')

    def test_portrait_and_raw_preview_reuse_file_without_encoding(self):
        with patch('app.preview.Image.open',side_effect=AssertionError('Unexpected transform')):
            for rotation,upright in [(0,True),(90,False),(270,False)]:
                response=preview_response(Path('screen-fixture.png'),rotation,upright)
                self.assertIsInstance(response,FileResponse)
                self.assertEqual(response.path,Path('screen-fixture.png'))

    def test_upright_preview_keeps_grayscale_render_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'screen.png'
            image=Image.new('L',(6,8),31)
            image.putpixel((2,3),97)
            image.save(path)
            response=preview_response(path,90,upright=True)
            with Image.open(BytesIO(response.body)) as restored:
                self.assertEqual(restored.mode,'L')
                self.assertEqual(set(restored.tobytes()),{31,97})
