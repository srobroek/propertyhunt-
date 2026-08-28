from __future__ import annotations
import asyncio,json
from pathlib import Path
from typing import Optional
import typer
from property_hunt.pipeline import run_pipeline
app=typer.Typer(no_args_is_help=True,help="Auditable UAE property hunting pipeline")
def execute(config:str,source:list[str]|None,max_price:float|None,output_dir:str,fixture_dir:str|None=None,allow_browser:bool=False):
 try:return asyncio.run(run_pipeline(config,source,max_price,output_dir,fixture_dir,allow_browser))
 except Exception as exc:typer.echo(f"fatal: {exc}",err=True);raise typer.Exit(1) from exc
def common(config:str,source:list[str]|None,max_price:float|None,output_dir:str,fixture_dir:str|None,verbose:bool,no_browser:bool):
 result=execute(config,source,max_price,output_dir,fixture_dir,not no_browser);typer.echo(json.dumps(result["counts"],indent=2) if verbose else f"candidates={result['counts']['candidates']}")
for command in ("fetch","normalize","compare","score","report","run"):
 def handler(config:str=typer.Option("config/hunt.yaml","--config"),source:Optional[list[str]]=typer.Option(None,"--source"),max_price:Optional[float]=typer.Option(None,"--max-price"),output_dir:str=typer.Option(".","--output-dir"),no_browser:bool=typer.Option(False,"--no-browser"),verbose:bool=typer.Option(False,"--verbose"),fixture_dir:Optional[str]=typer.Option(None,"--fixture-dir",hidden=True)):
  """Execute the selected deterministic pipeline stage (stages remain idempotent)."""; common(config,source,max_price,output_dir,fixture_dir,verbose,no_browser)
 handler.__name__=command;app.command(name=command)(handler)
if __name__=="__main__":app()
