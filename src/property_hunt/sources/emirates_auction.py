from .base import SourceAdapter,unsupported
class EmiratesAuctionAdapter(SourceAdapter):
    name="emirates_auction"
    async def fetch(self,**kwargs:object):
        return unsupported(self.name,"No stable, permission-verified public extraction endpoint; records intentionally omitted")
