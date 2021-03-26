class Image:
    id: str

class Container:
    image: Image

class Containers:
    def get(self, id: str) -> Container: ...

class Docker:
    containers: Containers

def from_env() -> Docker: ...
