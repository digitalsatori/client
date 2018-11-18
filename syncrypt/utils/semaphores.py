import asyncio
from typing import Generic, Set, TypeVar

T = TypeVar('T')


class JoinableSemaphore():
    def __init__(self, maxsize=0):
        self.count = 0
        self.limiter = asyncio.Semaphore(maxsize)
        self.empty = asyncio.Lock()

    async def acquire(self):
        if self.count == 0: await self.empty.acquire()
        self.count += 1
        await self.limiter.acquire()

    async def release(self):
        self.count -= 1
        if self.count == 0: self.empty.release()
        self.limiter.release()

    async def join(self):
        async with self.empty:
            pass


class JoinableSetSemaphore(JoinableSemaphore, Generic[T]): # pylint: disable=unsubscriptable-object
                                                           # https://github.com/PyCQA/pylint/issues/2416
    def __init__(self, maxsize=0):
        self.count = 0
        self.limiter = asyncio.Semaphore(maxsize)
        self.empty = asyncio.Lock()
        self._objects = set() # type: Set[T]

    @property
    def objects(self) -> Set[T]:
        return self._objects

    async def acquire(self, obj: T): # type: ignore
        if self.count == 0: await self.empty.acquire()
        self.count += 1
        await self.limiter.acquire()
        if obj in self._objects:
            raise ValueError('Object already acquired: %s' % obj)
        self._objects.add(obj)

    async def release(self, obj: T): # type: ignore
        self.count -= 1
        if self.count == 0: self.empty.release()
        self.limiter.release()
        self._objects.remove(obj)

    async def join(self):
        await self.empty
        if self.empty.locked(): self.empty.release()
