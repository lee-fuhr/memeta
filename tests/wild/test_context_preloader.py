"""Tests for F54: Context Pre-Loading"""

import pytest
import tempfile
import os
from datetime import datetime, timedelta

from memory_system.wild.context_preloader import ContextPreloader, PreloadTask


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def preloader(temp_db):
    return ContextPreloader(temp_db)


def test_preloader_initialization(preloader):
    assert preloader is not None


def test_schedule_preload(preloader):
    future = datetime.now() + timedelta(hours=1)
    task_id = preloader.schedule_preload(future, "client_meeting", "Test Client")
    assert task_id is not None


def test_get_pending_preloads_empty(preloader):
    tasks = preloader.get_pending_preloads()
    assert tasks == []


def test_get_pending_preloads_future(preloader):
    future = datetime.now() + timedelta(hours=1)
    preloader.schedule_preload(future, "client_meeting")
    tasks = preloader.get_pending_preloads()
    assert tasks == []  # Not ready yet


def test_get_pending_preloads_ready(preloader):
    past = datetime.now() - timedelta(hours=1)
    preloader.schedule_preload(past, "client_meeting")
    tasks = preloader.get_pending_preloads()
    assert len(tasks) == 1
    assert tasks[0].status == "pending"


def test_mark_loaded(preloader):
    past = datetime.now() - timedelta(hours=1)
    task_id = preloader.schedule_preload(past, "client_meeting")
    preloader.mark_loaded(task_id, ["mem1", "mem2"])
    
    memories = preloader.get_preloaded_context("client_meeting")
    assert len(memories) == 2


def test_mark_expired(preloader):
    past = datetime.now() - timedelta(hours=1)
    task_id = preloader.schedule_preload(past, "client_meeting")
    preloader.mark_expired(task_id)
    
    tasks = preloader.get_pending_preloads()
    assert len(tasks) == 0


def test_get_preloaded_context_empty(preloader):
    memories = preloader.get_preloaded_context("client_meeting")
    assert memories == []


def test_get_preloaded_context_with_target(preloader):
    past = datetime.now() - timedelta(hours=1)
    task_id = preloader.schedule_preload(past, "client_meeting", "Client A")
    preloader.mark_loaded(task_id, ["mem1"])
    
    memories = preloader.get_preloaded_context("client_meeting", "Client A")
    assert len(memories) == 1


def test_clear_preload_queue_recent_task(preloader):
    # Recent task should not be cleared
    past = datetime.now() - timedelta(hours=1)
    preloader.schedule_preload(past, "client_meeting")
    preloader.clear_preload_queue(older_than_days=7)
    
    stats = preloader.get_preload_statistics()
    assert stats["total"] == 1  # Task was created recently, not 10 days ago


def test_get_preload_statistics(preloader):
    past = datetime.now() - timedelta(hours=1)
    preloader.schedule_preload(past, "client_meeting")
    preloader.schedule_preload(past, "coding_session")
    
    stats = preloader.get_preload_statistics()
    assert stats["total"] == 2
    assert "by_status" in stats
    assert "by_context_type" in stats
