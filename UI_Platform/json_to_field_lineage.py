#!/usr/bin/env python3
"""Convert Informatica PowerCenter XML-as-JSON export to a Field_Lineage workbook.

Input JSON shape: {xml_declaration, doctype, root:{tag, attributes, children}}.
The parser builds a port-level directed graph from CONNECTOR records and adds
intra-transformation dependency edges obtained from TRANSFORMFIELD expressions.
It then enumerates source-to-target paths and emits the 12-column lineage format.

Usage:
  python json_to_field_lineage.py wf.json output.xlsx
  python json_to_field_lineage.py wf.json output.xlsx --reference sample.xlsx
"""
from __future__ import annotations
import argparse, json, re, sys
from collections import defaultdict, deque
from copy import copy
from pathlib import Path
from typing import Dict, Iterable, List, Tuple, Set
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

HEADERS = ["Mapping","Session","Source Table","Source Field","Target Table","Target Field",
           "Transformation","Transformation Type","Transformation_Full_Lineage_path",
           "Individual_Transformations","Links","Hop count"]
IDENT = re.compile(r"(?<![$.])\b[A-Za-z_][A-Za-z0-9_$]*\b")
SKIP_WORDS = {x.upper() for x in ("IIF ISNULL IN AND OR NOT TRUE FALSE NULL DECODE DATE_DIFF TO_DATE SELECT FROM WHERE CASE WHEN THEN ELSE END AS DISTINCT ORDER BY OVER PARTITION DESC ASC NULLS LAST DD YYYYMMDDHH24MISS").split()}

def children(n, tag=None):
    xs=n.get("children",[]) or []
    return [x for x in xs if tag is None or x.get("tag")==tag]
def attr(n,k,default=""): return (n.get("attributes",{}) or {}).get(k,default)
def walk(n):
    yield n
    for c in children(n): yield from walk(c)
def clean(v):
    if v is None: return ""
    return str(v).replace("_x000D_", "\n").replace("\r\n","\n").replace("\r","\n")
def norm(s): return str(s or "").strip().upper()
def tlabel(t):
    m={"EXPRESSION":"Expression","SOURCE QUALIFIER":"Source Qualifier","LOOKUP PROCEDURE":"Lookup",
       "AGGREGATOR":"Aggregator","JOINER":"Joiner","FILTER":"Filter","ROUTER":"Router",
       "UPDATE STRATEGY":"Update Strategy","SORTER":"Sorter","UNION":"Union","NORMALIZER":"Normalizer"}
    return m.get(norm(t), str(t or ""))

def find_folder(root):
    for n in walk(root):
        if n.get("tag")=="FOLDER": return n
    raise ValueError("FOLDER node not found")

def sessions(folder):
    out={}
    for n in walk(folder):
        if n.get("tag")=="SESSION": out[attr(n,"MAPPINGNAME")]=attr(n,"NAME")
    return out

def definitions(folder, tag, field_tag):
    d={}
    for n in children(folder, tag):
        d[attr(n,"NAME")]=[attr(f,"NAME") for f in children(n,field_tag)]
    return d

def table_attributes(tr):
    return {attr(x,"NAME"):clean(attr(x,"VALUE")) for x in children(tr,"TABLEATTRIBUTE")}

def expression_refs(expr, valid_names):
    refs=[]; valid={norm(x):x for x in valid_names}
    for tok in IDENT.findall(clean(expr)):
        u=norm(tok)
        if u in valid and u not in SKIP_WORDS and valid[u] not in refs: refs.append(valid[u])
    return refs

def parse_mapping(m, session_name, source_defs, target_defs):
    mapping=attr(m,"NAME")
    instances={attr(x,"NAME"):x for x in children(m,"INSTANCE")}
    transforms={attr(x,"NAME"):x for x in children(m,"TRANSFORMATION")}
    # node = (instance, field). External connector edges plus dependency edges inside transformations.
    fwd=defaultdict(list); rev=defaultdict(list); edge_kind={}
    def add(a,b,kind):
        if b not in fwd[a]: fwd[a].append(b); rev[b].append(a); edge_kind[(a,b)]=kind
    for c in children(m,"CONNECTOR"):
        add((attr(c,"FROMINSTANCE"),attr(c,"FROMFIELD")),(attr(c,"TOINSTANCE"),attr(c,"TOFIELD")),"connector")
    port_meta={}; tr_attrs={}; all_ports=defaultdict(list)
    for tn,tr in transforms.items():
        tr_attrs[tn]=table_attributes(tr)
        fs=children(tr,"TRANSFORMFIELD"); names=[attr(x,"NAME") for x in fs]
        all_ports[tn]=names
        for f in fs: port_meta[(tn,attr(f,"NAME"))]=f
        inputs=[attr(f,"NAME") for f in fs if "INPUT" in norm(attr(f,"PORTTYPE"))]
        for f in fs:
            outp=attr(f,"NAME"); pt=norm(attr(f,"PORTTYPE")); expr=attr(f,"EXPRESSION")
            if "OUTPUT" not in pt and not expr: continue
            refs=expression_refs(expr,names)
            if not refs:
                # pass-through ports normally retain the same name; otherwise REF_FIELD is authoritative.
                rf=attr(f,"REF_FIELD")
                refs=[rf] if rf in names else ([outp] if outp in inputs else [])
            for r in refs:
                if r!=outp or "INPUT/OUTPUT" in pt: add((tn,r),(tn,outp),"dependency")
    # source/target instance detection
    src_nodes=[]; tgt_nodes=[]
    src_table={}; tgt_table={}
    for name,ins in instances.items():
        typ=norm(attr(ins,"TYPE")); trans=attr(ins,"TRANSFORMATION_NAME") or name
        if typ=="SOURCE":
            src_table[name]=trans
            fields=source_defs.get(trans,[])
            # only connected fields are needed; include defs for completeness
            used={p for i,p in fwd if i==name}
            for p in fields:
                if not used or p in used: src_nodes.append((name,p))
        elif typ=="TARGET":
            tgt_table[name]=trans
            fields=target_defs.get(trans,[])
            used={p for i,p in rev if i==name}
            for p in fields:
                if not used or p in used: tgt_nodes.append((name,p))
    # enumerate backward from each target; cap protects malformed cyclic mappings
    pathset=set(); paths=[]
    source_set=set(src_nodes)
    def dfs(cur, acc, seen):
        if len(acc)>80: return
        if cur in source_set:
            p=tuple(reversed(acc+[cur]))
            if p not in pathset: pathset.add(p); paths.append(p)
            return
        for prev in rev.get(cur,[]):
            if prev not in seen: dfs(prev,acc+[cur],seen|{prev})
    for t in tgt_nodes: dfs(t,[],{t})
    rows=[]
    for path in paths:
        s,t=path[0],path[-1]
        visible=[]
        for n in path:
            if not visible or visible[-1]!=n: visible.append(n)
        lineage=" -> ".join(f"{i}.{p}" for i,p in visible)
        hops=max(0,len(visible)-1)
        # transformation rows in path order, unique port/expression combinations
        details=[]; seen_det=set()
        for i,p in visible[1:-1]:
            if i not in transforms: continue
            tr=transforms[i]; typ=tlabel(attr(tr,"TYPE")); f=port_meta.get((i,p)); expr=clean(attr(f,"EXPRESSION")) if f else ""
            key=(i,expr)
            if key not in seen_det:
                seen_det.add(key); details.append((i,typ,("EXPRESSION: "+expr) if expr else ""))
            if norm(attr(tr,"TYPE"))=="SOURCE QUALIFIER":
                sql=tr_attrs.get(i,{}).get("Sql Query") or tr_attrs.get(i,{}).get("SQL Query") or tr_attrs.get(i,{}).get("SQL_QUERY")
                if sql:
                    key=(i,"SQL_QUERY: "+sql)
                    if key not in seen_det: seen_det.add(key); details.append((i,typ,"SQL_QUERY: "+sql))
        if not details: details=[("","","")]
        for tn,typ,individual in details:
            rows.append([mapping,session_name,src_table.get(s[0],s[0]),s[1],tgt_table.get(t[0],t[0]),t[1],
                         tn,typ,lineage,individual,"",hops])
    return rows

def write_xlsx(rows, output, reference=None):
    if reference:
        ref=load_workbook(reference); ws0=ref[ref.sheetnames[0]]
        wb=Workbook(); ws=wb.active; ws.title=ws0.title
        for c,cell in enumerate(ws0[1],1):
            x=ws.cell(1,c,HEADERS[c-1]); x._style=copy(cell._style); x.number_format=cell.number_format
        for c,dim in ws0.column_dimensions.items(): ws.column_dimensions[c].width=dim.width
        ws.freeze_panes=ws0.freeze_panes; ws.sheet_view.showGridLines=ws0.sheet_view.showGridLines
    else:
        wb=Workbook(); ws=wb.active; ws.title="Field_Lineage"
        for c,h in enumerate(HEADERS,1):
            x=ws.cell(1,c,h); x.font=Font(bold=True,color="FFFFFF"); x.fill=PatternFill("solid",fgColor="1F4E78")
            x.alignment=Alignment(wrap_text=True,vertical="top")
        widths=[30,32,36,30,36,30,28,22,90,70,15,12]
        for i,w in enumerate(widths,1): ws.column_dimensions[get_column_letter(i)].width=w
        ws.freeze_panes="A2"; ws.auto_filter.ref="A1:L1"
    for r,row in enumerate(rows,2):
        for c,v in enumerate(row,1):
            ws.cell(r,c,v).alignment=Alignment(vertical="top",wrap_text=c in (9,10))
    wb.save(output)

def compare(actual, reference):
    a=load_workbook(actual,read_only=True,data_only=False).active
    b=load_workbook(reference,read_only=True,data_only=False).active
    mism=0; examples=[]
    mr=max(a.max_row,b.max_row); mc=max(a.max_column,b.max_column)
    for r in range(1,mr+1):
        for c in range(1,mc+1):
            av=a.cell(r,c).value; bv=b.cell(r,c).value
            if av!=bv:
                mism+=1
                if len(examples)<20: examples.append((r,c,av,bv))
    return {"actual_shape":[a.max_row,a.max_column],"reference_shape":[b.max_row,b.max_column],"cell_mismatches":mism,"examples":examples}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("json_file"); ap.add_argument("output_xlsx"); ap.add_argument("--reference")
    args=ap.parse_args()
    data=json.load(open(args.json_file,encoding="utf-8")); folder=find_folder(data["root"])
    sess=sessions(folder); sdefs=definitions(folder,"SOURCE","SOURCEFIELD"); tdefs=definitions(folder,"TARGET","TARGETFIELD")
    rows=[]
    for m in children(folder,"MAPPING"):
        rows.extend(parse_mapping(m,sess.get(attr(m,"NAME"),""),sdefs,tdefs))
    # stable deterministic order; preserves mapping discovery, then target/source/path/transformation
    rows.sort(key=lambda r:(r[0],r[4],r[5],r[2],r[3],r[8],r[6],r[9]))
    write_xlsx(rows,args.output_xlsx,args.reference)
    print(f"Wrote {len(rows)} lineage rows to {args.output_xlsx}")
    if args.reference:
        report=compare(args.output_xlsx,args.reference)
        rp=str(Path(args.output_xlsx).with_suffix(".comparison.json"))
        json.dump(report,open(rp,"w",encoding="utf-8"),indent=2,default=str)
        print(f"Comparison report: {rp}; mismatches={report['cell_mismatches']}")
if __name__=="__main__": main()
