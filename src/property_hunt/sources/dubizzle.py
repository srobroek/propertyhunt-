from .base import SourceAdapter,unsupported
class DubizzleAdapter(SourceAdapter):
    name="dubizzle"
    async def fetch(self,**kwargs:object):
        return unsupported(self.name,"No stable, permission-verified public extraction endpoint; records intentionally omitted")
