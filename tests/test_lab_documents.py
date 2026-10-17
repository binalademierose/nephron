"""
Checks for services/lab_documents.py: saving an uploaded file to disk. No Flask, no database - a tiny stand-in
for werkzeug's FileStorage (just .read() and .filename) is enough. Run everything with: python -m unittest discover -s tests -v
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import lab_documents  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
REAL_PNG = os.path.join(FIXTURES, "sample_lab_report.png")
REAL_PDF = os.path.join(FIXTURES, "sample_lab_report.pdf")


class FakeUpload:
    """A stand-in for werkzeug's FileStorage: just enough for save_upload (.read(), .filename)."""

    def __init__(self, data, filename="upload"):
        self._data = data
        self.filename = filename

    def read(self):
        return self._data


def real_bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


class SniffContentTypeTests(unittest.TestCase):
    def test_recognises_the_three_accepted_types_from_their_own_bytes(self):
        self.assertEqual(lab_documents.sniff_content_type(b"\xff\xd8\xff" + b"0" * 20), "image/jpeg")
        self.assertEqual(lab_documents.sniff_content_type(b"\x89PNG\r\n\x1a\n" + b"0" * 20), "image/png")
        self.assertEqual(lab_documents.sniff_content_type(b"%PDF-1.4" + b"0" * 20), "application/pdf")

    def test_anything_else_is_not_recognised(self):
        self.assertIsNone(lab_documents.sniff_content_type(b"just some text"))
        self.assertIsNone(lab_documents.sniff_content_type(b""))


class SaveUploadTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.directory, True)

    def test_a_real_png_is_saved_with_a_random_name_never_the_original(self):
        stored, content_type, original = lab_documents.save_upload(FakeUpload(real_bytes(REAL_PNG), "my labs.png"), self.directory)
        self.assertEqual(content_type, "image/png")
        self.assertEqual(original, "my labs.png")
        self.assertTrue(stored.endswith(".png"))
        self.assertNotIn("my labs", stored)
        self.assertNotIn(" ", stored)
        with open(os.path.join(self.directory, stored), "rb") as handle:
            self.assertEqual(handle.read(), real_bytes(REAL_PNG))

    def test_a_real_pdf_is_saved_too(self):
        stored, content_type, _ = lab_documents.save_upload(FakeUpload(real_bytes(REAL_PDF), "labs.pdf"), self.directory)
        self.assertEqual(content_type, "application/pdf")
        self.assertTrue(stored.endswith(".pdf"))

    def test_two_uploads_never_collide_on_the_same_stored_name(self):
        first, _, _ = lab_documents.save_upload(FakeUpload(real_bytes(REAL_PNG)), self.directory)
        second, _, _ = lab_documents.save_upload(FakeUpload(real_bytes(REAL_PNG)), self.directory)
        self.assertNotEqual(first, second)

    def test_a_file_claiming_to_be_an_image_but_is_not_is_refused(self):
        with self.assertRaisesRegex(lab_documents.RejectedUpload, "JPEG, PNG or PDF"):
            lab_documents.save_upload(FakeUpload(b"not an image at all", "totally-a-photo.jpg"), self.directory)
        self.assertEqual(os.listdir(self.directory), [])          # nothing was written for a refused upload

    def test_an_empty_file_is_refused(self):
        with self.assertRaisesRegex(lab_documents.RejectedUpload, "empty"):
            lab_documents.save_upload(FakeUpload(b"", "empty.png"), self.directory)

    def test_a_file_over_the_size_limit_is_refused_even_with_a_real_png_header(self):
        oversized = b"\x89PNG\r\n\x1a\n" + b"0" * (lab_documents.MAX_UPLOAD_BYTES + 1)
        with self.assertRaisesRegex(lab_documents.RejectedUpload, "10 MB"):
            lab_documents.save_upload(FakeUpload(oversized, "huge.png"), self.directory)

    def test_a_file_right_at_the_size_limit_is_accepted(self):
        exactly = b"\x89PNG\r\n\x1a\n" + b"0" * (lab_documents.MAX_UPLOAD_BYTES - 8)
        stored, _, _ = lab_documents.save_upload(FakeUpload(exactly, "exact.png"), self.directory)
        self.assertTrue(os.path.exists(os.path.join(self.directory, stored)))

    def test_the_claimed_extension_never_decides_the_saved_type_the_real_bytes_do(self):
        # A real PNG's bytes, dishonestly named as if it were a PDF: it is saved as what it REALLY is.
        stored, content_type, _ = lab_documents.save_upload(FakeUpload(real_bytes(REAL_PNG), "labs.pdf"), self.directory)
        self.assertEqual(content_type, "image/png")
        self.assertTrue(stored.endswith(".png"))

    def test_a_filesystem_error_while_saving_is_a_clear_message_not_a_crash(self):
        from unittest import mock
        with mock.patch("os.makedirs", side_effect=PermissionError(5, "Access is denied")):
            with self.assertRaisesRegex(lab_documents.RejectedUpload, "could not be saved"):
                lab_documents.save_upload(FakeUpload(real_bytes(REAL_PNG)), self.directory)
        self.assertEqual(os.listdir(self.directory), [])          # nothing half-written was left behind

    def test_upload_dir_is_created_if_it_does_not_exist_yet(self):
        fresh = os.path.join(self.directory, "not-yet-created")
        lab_documents.save_upload(FakeUpload(real_bytes(REAL_PNG)), fresh)
        self.assertTrue(os.path.isdir(fresh))

    def test_a_missing_filename_does_not_crash_a_placeholder_is_used(self):
        upload = FakeUpload(real_bytes(REAL_PNG))
        upload.filename = None
        _, _, original = lab_documents.save_upload(upload, self.directory)
        self.assertTrue(original)


class PathForTests(unittest.TestCase):
    def test_joins_the_upload_directory_and_the_stored_name(self):
        self.assertEqual(lab_documents.path_for("/some/dir", "abc.png"), os.path.join("/some/dir", "abc.png"))


if __name__ == "__main__":
    unittest.main()
