'''
 *
 *      rbtree.py
 *      Left-leaning red-black (LLRB) balanced binary search tree.
 *
 *      A fresh implementation of the LLRB 2-3 tree from Robert Sedgewick's
 *      "Left-Leaning Red-Black Trees" (2008): the paper that finally gave a
 *      complete, short specification of delete(), which classic red-black
 *      write-ups leave as case-by-case exercises. The algorithm keeps the
 *      extra invariant that every red link leans left (except transiently
 *      during updates), giving a 1-1 correspondence with 2-3 trees; insert
 *      and delete stay O(log n) with no parent pointers and no extra space.
 *
 *      The scheduler's run queue uses this for its deadline index, walking
 *      it in key order with early exit. Unlike a lazy heap that pops and
 *      re-pushes entries on every pick, the in-order walk never mutates
 *      the structure, so the common case costs a few pointer hops.
 *
 *      2026/10/11 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

from typing import Any, Iterator, Optional, Tuple

RED = True
BLACK = False


# A tree node: key/value pair plus the colour of the link from its parent.
class _Node:
    __slots__ = ("key", "val", "color", "left", "right")

    def __init__(self, key: Any, val: Any, color: bool = RED):
        self.key = key
        self.val = val
        self.color = color           # new links are always red
        self.left: Optional[_Node] = None
        self.right: Optional[_Node] = None


# A null link counts as black, which is what keeps the recursion guard-free.
def _is_red(h: Optional[_Node]) -> bool:
    return h is not None and h.color == RED


# Left-leaning red-black symbol table with a dict-like surface.
class RBTree:
    # Create an empty tree.
    def __init__(self):
        self._root: Optional[_Node] = None
        self._count = 0

    def __len__(self) -> int:
        return self._count

    def __contains__(self, key: Any) -> bool:
        return self._find(key) is not None

    # -- lookup ---------------------------------------------------------

    # Return the node carrying key, or None.
    def _find(self, key: Any) -> Optional[_Node]:
        h = self._root
        while h is not None:
            if key < h.key:
                h = h.left
            elif key > h.key:
                h = h.right
            else:
                return h
        return None

    # Return the value for key, default when missing.
    def get(self, key: Any, default: Any = None) -> Any:
        h = self._find(key)
        return default if h is None else h.val

    # Return the (key, value) pair with the smallest key, or None when empty.
    def minimum(self) -> Optional[Tuple[Any, Any]]:
        h = self._root
        if h is None:
            return None
        while h.left is not None:
            h = h.left
        return (h.key, h.val)

    # Yield (key, value) pairs in ascending key order, with an explicit
    # stack so the walk costs O(1) amortised per step and exits early.
    def __iter__(self) -> Iterator[Tuple[Any, Any]]:
        stack = []
        h = self._root
        while stack or h is not None:
            if h is not None:
                stack.append(h)
                h = h.left
            else:
                h = stack.pop()
                yield (h.key, h.val)
                h = h.right

    # -- hot ordered walk --------------------------------------------------

    # Return the first (key, value) in key order whose value is eligible,
    # or None. This is the tick hot path behind the scheduler's picks, so
    # it is a plain loop, not a generator: no per-step frame switch, and
    # the predicate is inlined instead of called.
    #
    # Contract with the scheduler: keys are (deadline, vruntime, pid) and
    # every node in the tree is RUNNING (removal is a real delete on every
    # state exit), so no state check is needed per visit. deadline_lt cuts
    # the walk off once keys can no longer beat the running task.
    def first_eligible(self, avg: float,
                       deadline_lt: Optional[float] = None) -> Optional[Tuple[Any, Any]]:
        eps = 1e-9
        stack = []
        h = self._root
        while stack or h is not None:
            while h is not None:
                stack.append(h)
                h = h.left
            h = stack.pop()
            if deadline_lt is not None and h.key[0] >= deadline_lt:
                return None
            if h.val.vruntime <= avg + eps:
                return (h.key, h.val)
            h = h.right
        return None

    # -- rotations and colour flips -------------------------------------

    # Lean a right-leaning red link to the left.
    @staticmethod
    def _rotate_left(h: _Node) -> _Node:
        x = h.right
        h.right = x.left
        x.left = h
        x.color, h.color = h.color, RED
        return x

    # Balance a left-leaning pair of red links.
    @staticmethod
    def _rotate_right(h: _Node) -> _Node:
        x = h.left
        h.left = x.right
        x.right = h
        x.color, h.color = h.color, RED
        return x

    # Split a temporary 4-node; both children must exist here.
    @staticmethod
    def _flip_colors(h: _Node) -> None:
        h.color = not h.color
        h.left.color = not h.left.color
        h.right.color = not h.right.color

    # -- insert ----------------------------------------------------------

    # Insert key/value, replacing the value when the key is already present.
    def insert(self, key: Any, val: Any = None) -> None:
        self._root, added = self._put(self._root, key, val)
        if added:
            self._count += 1
        self._root.color = BLACK

    # Recursive BST insert plus, on the way back up, the three LLRB fixes:
    # lean right reds left, balance double left reds, split 4-nodes.
    # Note the first guard differs from _fix_up() on purpose: on the insert
    # path a both-children-red node must split, not rotate; _fix_up() is the
    # delete-path variant where that shape cannot arrive unprepared.
    def _put(self, h: Optional[_Node], key: Any, val: Any) -> Tuple[_Node, bool]:
        if h is None:
            return _Node(key, val), True
        if key < h.key:
            h.left, added = self._put(h.left, key, val)
        elif key > h.key:
            h.right, added = self._put(h.right, key, val)
        else:
            h.val = val
            added = False
        if _is_red(h.right) and not _is_red(h.left):
            h = self._rotate_left(h)
        if _is_red(h.left) and _is_red(h.left.left):
            h = self._rotate_right(h)
        if _is_red(h.left) and _is_red(h.right):
            self._flip_colors(h)
        return h, added
    # -- delete ----------------------------------------------------------

    # Remove the smallest key; the tree must not be empty.
    def delete_min(self) -> None:
        if self._root is None:
            raise KeyError("delete_min() of an empty tree")
        if not _is_red(self._root.left) and not _is_red(self._root.right):
            self._root.color = RED
        self._root = self._delete_min(self._root)
        self._count -= 1
        if self._root is not None:
            self._root.color = BLACK

    # Delete the bottom node of the left spine, borrowing a red link from
    # the right whenever the left child and grandchild are both black.
    def _delete_min(self, h: _Node) -> Optional[_Node]:
        if h.left is None:
            return None
        if not _is_red(h.left) and not _is_red(h.left.left):
            h = self._move_red_left(h)
        h.left = self._delete_min(h.left)
        return self._fix_up(h)

    # Remove key, raising KeyError when it is not in the tree.
    # The existence check comes first on purpose: the recursive delete
    # below assumes the key is present, and its down-the-path rotations
    # would otherwise corrupt the tree while hunting a missing key.
    def delete(self, key: Any) -> None:
        if self._root is None or self._find(key) is None:
            raise KeyError(key)
        if not _is_red(self._root.left) and not _is_red(self._root.right):
            self._root.color = RED
        self._root = self._delete(self._root, key)
        self._count -= 1
        if self._root is not None:
            self._root.color = BLACK

    # Full LLRB delete: rotations and colour flips on the way down keep the
    # search off 2-nodes, so the node at the bottom can simply be dropped;
    # fix_up() repairs the transient right-leaning links on the way back up.
    def _delete(self, h: _Node, key: Any) -> Optional[_Node]:
        if key < h.key:
            if h.left is None:
                raise KeyError(key)
            if not _is_red(h.left) and not _is_red(h.left.left):
                h = self._move_red_left(h)
            h.left = self._delete(h.left, key)
        else:
            if _is_red(h.left):
                h = self._rotate_right(h)
            if key == h.key and h.right is None:
                return None
            if h.right is None:
                raise KeyError(key)
            if not _is_red(h.right) and not _is_red(h.right.left):
                h = self._move_red_right(h)
            if key == h.key:
                succ = h.right
                while succ.left is not None:
                    succ = succ.left
                h.key, h.val = succ.key, succ.val
                h.right = self._delete_min(h.right)
            else:
                h.right = self._delete(h.right, key)
        return self._fix_up(h)

    # Repair helper shared by insert and delete: lean right reds left,
    # balance double left reds, split 4-nodes.
    def _fix_up(self, h: _Node) -> _Node:
        if _is_red(h.right):
            h = self._rotate_left(h)
        if _is_red(h.left) and _is_red(h.left.left):
            h = self._rotate_right(h)
        if _is_red(h.left) and _is_red(h.right):
            self._flip_colors(h)
        return h

    # Assuming h is red and h.left plus h.left.left are black, make h.left
    # or one of its children red so the search can move left.
    def _move_red_left(self, h: _Node) -> _Node:
        self._flip_colors(h)
        if _is_red(h.right.left):
            h.right = self._rotate_right(h.right)
            h = self._rotate_left(h)
            self._flip_colors(h)
        return h

    # Assuming h is red and h.right plus h.right.left are black, make
    # h.right or one of its children red so the search can move right.
    def _move_red_right(self, h: _Node) -> _Node:
        self._flip_colors(h)
        if _is_red(h.left.left):
            h = self._rotate_right(h)
            self._flip_colors(h)
        return h

    # -- self-verification -------------------------------------------------

    # Verify BST order, the 2-3 shape (no right red links, no double left
    # reds) and black-balance; raises AssertionError naming the violation.
    # The scheduler's fuzz tests call this after every batch of updates.
    def check(self) -> bool:
        if self._root is not None and self._root.color != BLACK:
            raise AssertionError("root must be black")
        if not self._is_bst(self._root, None, None):
            raise AssertionError("keys out of order")
        if not self._is_23(self._root, True):
            raise AssertionError("not a 2-3 tree: right-leaning or double red link")
        _, ok = self._black_height(self._root)
        if not ok:
            raise AssertionError("black heights differ")
        count = sum(1 for _ in self)
        if count != self._count:
            raise AssertionError(f"count {self._count} != iterated {count}")
        return True

    def _is_bst(self, h: Optional[_Node], lo: Any, hi: Any) -> bool:
        if h is None:
            return True
        if lo is not None and not h.key > lo:
            return False
        if hi is not None and not h.key < hi:
            return False
        return self._is_bst(h.left, lo, h.key) and self._is_bst(h.right, h.key, hi)

    def _is_23(self, h: Optional[_Node], is_root: bool) -> bool:
        if h is None:
            return True
        if _is_red(h.right):
            return False
        if not is_root and _is_red(h) and _is_red(h.left):
            return False
        return self._is_23(h.left, False) and self._is_23(h.right, False)

    # Return (black height, balanced) for the subtree.
    def _black_height(self, h: Optional[_Node]) -> Tuple[int, bool]:
        if h is None:
            return (1, True)
        left, ok_left = self._black_height(h.left)
        right, ok_right = self._black_height(h.right)
        add = 0 if _is_red(h) else 1
        return (left + add, ok_left and ok_right and left == right)
