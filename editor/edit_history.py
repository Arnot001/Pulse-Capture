"""Bounded undo/redo for immutable editor snapshots, with grouped pointer drags."""
from dataclasses import dataclass


@dataclass(frozen=True)
class EditSnapshot:
    trim: object
    cuts: object
    edits: object


class EditHistory:
    def __init__(self, initial, limit=100):
        self.current=initial
        self.past=[]
        self.future=[]
        self.limit=limit
        self.group=None

    def begin(self):
        if self.group is None:self.group=self.current

    def record(self, state):
        if state==self.current:return False
        if self.group is None:
            self.past.append(self.current)
            self.past=self.past[-self.limit:]
        self.current=state
        self.future.clear()
        return True

    def end(self):
        before,self.group=self.group,None
        if before is not None and before!=self.current:
            self.past.append(before)
            self.past=self.past[-self.limit:]

    def undo(self):
        self.end()
        if self.past:
            self.future.append(self.current)
            self.current=self.past.pop()
        return self.current

    def redo(self):
        if self.future:
            self.past.append(self.current)
            self.current=self.future.pop()
        return self.current
