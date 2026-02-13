"""Tests for F56: Client Pattern Transfer"""

import pytest
import tempfile
import os

from src.wild.pattern_transfer import PatternTransferer, PatternTransfer


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def transferer(temp_db):
    return PatternTransferer(temp_db)


def test_transferer_initialization(transferer):
    assert transferer is not None


def test_transfer_pattern(transferer):
    transfer_id = transferer.transfer_pattern("Client A", "Client B", "Pattern description")
    assert transfer_id is not None


def test_rate_transfer(transferer):
    transfer_id = transferer.transfer_pattern("Client A", "Client B", "Pattern")
    transferer.rate_transfer(transfer_id, 0.8, "Worked well")


def test_rate_transfer_invalid_rating(transferer):
    transfer_id = transferer.transfer_pattern("Client A", "Client B", "Pattern")
    with pytest.raises(ValueError):
        transferer.rate_transfer(transfer_id, 1.5)


def test_get_transfer_history_empty(transferer):
    history = transferer.get_transfer_history()
    assert history == []


def test_get_transfer_history_with_data(transferer):
    transferer.transfer_pattern("Client A", "Client B", "Pattern 1")
    transferer.transfer_pattern("Client B", "Client C", "Pattern 2")
    
    history = transferer.get_transfer_history()
    assert len(history) == 2


def test_get_transfer_history_filtered(transferer):
    transferer.transfer_pattern("Client A", "Client B", "Pattern 1")
    transferer.transfer_pattern("Client B", "Client C", "Pattern 2")
    
    history = transferer.get_transfer_history("Client A")
    assert len(history) == 1


def test_get_successful_transfers(transferer):
    t1 = transferer.transfer_pattern("Client A", "Client B", "Pattern 1")
    t2 = transferer.transfer_pattern("Client A", "Client C", "Pattern 2")
    
    transferer.rate_transfer(t1, 0.9)
    transferer.rate_transfer(t2, 0.5)
    
    successful = transferer.get_successful_transfers(min_rating=0.7)
    assert len(successful) == 1
    assert successful[0].effectiveness_rating == 0.9


def test_find_transferable_patterns_empty(transferer):
    patterns = transferer.find_transferable_patterns("Client A", "Client B")
    assert patterns == []


def test_find_transferable_patterns_with_data(transferer):
    t_id = transferer.transfer_pattern("Client A", "Client B", "Good pattern")
    transferer.rate_transfer(t_id, 0.9)
    
    patterns = transferer.find_transferable_patterns("Client A", "Client C")
    assert len(patterns) == 1
