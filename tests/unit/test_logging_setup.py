"""Unit tests for src/logging_setup.py"""
import gzip
import logging
import os
import pathlib

import pytest

from src.logging_setup import (
    _gz_namer,
    _gz_rotator,
    _parse_level,
    configure_logging,
)


class TestParseLevel:
    def test_valid_info(self):
        assert _parse_level("INFO") == logging.INFO

    def test_valid_debug(self):
        assert _parse_level("DEBUG") == logging.DEBUG

    def test_valid_warning(self):
        assert _parse_level("WARNING") == logging.WARNING

    def test_valid_error(self):
        assert _parse_level("ERROR") == logging.ERROR

    def test_case_insensitive(self):
        assert _parse_level("debug") == logging.DEBUG
        assert _parse_level("Info") == logging.INFO

    def test_unknown_falls_back_to_info(self):
        assert _parse_level("VERBOSE") == logging.INFO

    def test_empty_falls_back_to_info(self):
        assert _parse_level("") == logging.INFO


class TestConfigureLogging:
    def setup_method(self):
        # Reset root logger before each test
        root = logging.getLogger()
        root.handlers.clear()

    def test_stdout_handler_always_added(self):
        configure_logging("INFO", "")
        root = logging.getLogger()
        stream_handlers = [h for h in root.handlers if isinstance(h, logging.StreamHandler)
                           and not isinstance(h, logging.FileHandler)]
        assert len(stream_handlers) == 1

    def test_no_file_handler_when_log_dir_empty(self):
        configure_logging("INFO", "")
        root = logging.getLogger()
        file_handlers = [h for h in root.handlers if isinstance(h, logging.FileHandler)]
        assert len(file_handlers) == 0

    def test_file_handler_added_when_log_dir_set(self, tmp_path):
        configure_logging("INFO", str(tmp_path))
        root = logging.getLogger()
        file_handlers = [h for h in root.handlers if isinstance(h, logging.FileHandler)]
        assert len(file_handlers) == 1

    def test_log_file_created_in_log_dir(self, tmp_path):
        configure_logging("INFO", str(tmp_path))
        logging.getLogger("test").info("hello")
        assert (tmp_path / "agentgate.log").exists()

    def test_log_dir_created_if_missing(self, tmp_path):
        new_dir = tmp_path / "subdir" / "logs"
        configure_logging("INFO", str(new_dir))
        assert new_dir.exists()

    def test_log_level_applied(self):
        configure_logging("WARNING", "")
        assert logging.getLogger().level == logging.WARNING

    def test_existing_handlers_replaced(self):
        logging.getLogger().addHandler(logging.StreamHandler())
        configure_logging("INFO", "")
        root = logging.getLogger()
        # Should have exactly 1 handler after configure
        assert len(root.handlers) == 1

    def test_formatter_uses_iso_timestamp(self):
        configure_logging("INFO", "")
        root = logging.getLogger()
        handler = root.handlers[0]
        assert handler.formatter.datefmt == "%Y-%m-%dT%H:%M:%S"


class TestGzHelpers:
    def test_gz_namer_appends_gz(self):
        assert _gz_namer("agentgate.log.2026-03-07") == "agentgate.log.2026-03-07.gz"

    def test_gz_rotator_compresses_and_removes_source(self, tmp_path):
        source = tmp_path / "agentgate.log.2026-03-07"
        dest = tmp_path / "agentgate.log.2026-03-07.gz"
        source.write_text("some log content")
        _gz_rotator(str(source), str(dest))
        assert not source.exists()
        assert dest.exists()
        # Verify the compressed file is valid gzip
        with gzip.open(str(dest), "rt") as f:
            assert f.read() == "some log content"
