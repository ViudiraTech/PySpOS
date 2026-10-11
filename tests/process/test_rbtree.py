'''
 *
 *      test_rbtree.py
 *      LLRB red-black tree: ordering, delete and invariant fuzzing against
 *      a sorted-list oracle.
 *
 *      2026/10/11 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import random

import pytest

from rbtree import BLACK, RBTree


# Fresh keys must come out in ascending order and report their size.
def test_insert_orders_and_counts():
    tree = RBTree()
    for key in (5, 3, 7, 1, 9, 2):
        tree.insert(key, key * 10)
    assert [k for k, _ in tree] == [1, 2, 3, 5, 7, 9]
    assert len(tree) == 6
    assert tree.minimum() == (1, 10)
    assert 7 in tree and 42 not in tree
    assert tree.get(5) == 50 and tree.get(42, "dflt") == "dflt"
    tree.check()


# Re-inserting a key replaces its value without growing the tree.
def test_duplicate_key_replaces_value():
    tree = RBTree()
    tree.insert("a", 1)
    tree.insert("a", 2)
    assert len(tree) == 1
    assert tree.get("a") == 2
    tree.check()


# Deleting every key empties the tree in order; missing keys raise.
def test_delete_empties_in_order():
    tree = RBTree()
    for key in (4, 2, 6, 1, 3, 5, 7):
        tree.insert(key)
    for expect in (1, 2, 3, 4, 5, 6, 7):
        tree.delete(expect)
        tree.check()
        rest = [k for k, _ in tree]
        assert rest == sorted(rest) and expect not in rest
    assert len(tree) == 0
    assert tree.minimum() is None
    assert list(tree) == []
    with pytest.raises(KeyError):
        tree.delete(1)
    with pytest.raises(KeyError):
        tree.delete_min()


# Deleting an internal node with two children keeps the order intact.
def test_delete_internal_two_child_node():
    tree = RBTree()
    for key in range(15):
        tree.insert(key, key)
    gone = set()
    for victim in (7, 3, 11, 0, 14):
        tree.delete(victim)
        gone.add(victim)
        tree.check()
        assert [k for k, _ in tree] == [k for k in range(15) if k not in gone]
    assert len(tree) == 10


# Scheduler-shaped tuple keys compare deadline first, then vruntime, pid.
def test_tuple_keys_match_pick_order():
    tree = RBTree()
    keys = [(3.0, 1.0, 9), (1.0, 5.0, 3), (1.0, 2.0, 4), (2.0, 0.0, 7)]
    for key in keys:
        tree.insert(key, key[2])
    assert [v for _, v in tree] == [4, 3, 7, 9]
    assert tree.minimum() == ((1.0, 2.0, 4), 4)
    tree.check()


# Random inserts and deletes must always match a sorted-list oracle,
# with the red-black invariants verified after every batch.
@pytest.mark.parametrize("seed", [20261011, 1, 987654])
def test_fuzz_against_sorted_oracle(seed):
    rng = random.Random(seed)
    tree = RBTree()
    oracle = {}
    for step in range(4000):
        op = rng.random()
        if op < 0.55 or not oracle:
            key = (rng.random(), rng.random(), rng.randrange(10 ** 6))
            val = rng.randrange(10 ** 6)
            tree.insert(key, val)
            oracle[key] = val
        elif op < 0.85:
            key = rng.choice(list(oracle))
            tree.delete(key)
            del oracle[key]
        else:
            key = (rng.random(), rng.random(), rng.randrange(10 ** 6))
            if key not in oracle:
                with pytest.raises(KeyError):
                    tree.delete(key)
        if step % 50 == 0:
            tree.check()
            assert len(tree) == len(oracle)
            assert [k for k, _ in tree] == sorted(oracle)
            if oracle:
                assert tree.minimum()[0] == min(oracle)
    tree.check()
    assert [k for k, _ in tree] == sorted(oracle)


# Deleting in ascending and descending runs stresses the spine paths.
@pytest.mark.parametrize("order", ["ascending", "descending", "shuffled"])
def test_delete_runs_keep_balance(order):
    keys = list(range(300))
    if order == "shuffled":
        rng = random.Random(7)
        rng.shuffle(keys)
    tree = RBTree()
    for key in keys:
        tree.insert(key)
    tree.check()
    victims = list(range(300))
    if order == "descending":
        victims.reverse()
    elif order == "shuffled":
        rng = random.Random(9)
        rng.shuffle(victims)
    for i, victim in enumerate(victims):
        tree.delete(victim)
        if i % 25 == 0:
            tree.check()
    assert len(tree) == 0
    assert tree._root is None


# The hot ordered walk skips ineligible prefixes and honours the bound.
def test_first_eligible_walk():
    from types import SimpleNamespace
    tree = RBTree()
    assert tree.first_eligible(10.0) is None
    entries = {(1.0, 9.0, 1): 50.0, (2.0, 1.0, 2): 5.0,
               (3.0, 2.0, 3): 8.0, (4.0, 0.0, 4): 30.0}
    for key, vruntime in entries.items():
        tree.insert(key, SimpleNamespace(vruntime=vruntime))
    assert tree.first_eligible(10.0)[0] == (2.0, 1.0, 2)
    assert tree.first_eligible(4.0) is None
    assert tree.first_eligible(10.0, deadline_lt=2.5)[0] == (2.0, 1.0, 2)
    assert tree.first_eligible(10.0, deadline_lt=2.0) is None
    assert tree.first_eligible(10.0, deadline_lt=1.0) is None
    assert tree.first_eligible(100.0, deadline_lt=2.5)[0] == (1.0, 9.0, 1)
    tree.check()


# The tree object exposes the black root the algorithm requires.
def test_root_is_black():
    tree = RBTree()
    for key in (10, 5, 15, 3, 7):
        tree.insert(key)
        assert tree._root.color == BLACK
