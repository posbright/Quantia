import{q as ue,j as fe,ap as me,V as pe,Z as _e,a4 as ye,b as ve,aq as ge,p as ke,n as be,ar as we,as as xe,W as he,at as Ce,au as Te,D as Ee,k as Se,a as r,ao as O}from"./vendor-element-B6ScSKQd.js";import{d as De,m as Fe,c as x,J as F,a as z,H as Ae,A as k,r as m,P as l,G as o,M as b,b as N,o as u,L as d,u as A,O as Be,a5 as Ve,al as ze,ay as Ie,n as Ke}from"./vendor-vue-D92-bNgp.js";import{c as Me,r as j,e as q,s as Y,f as Ne,h as Re,i as Pe,m as Le,j as $e,k as Ge}from"./stock-CUMyrWfX.js";import{_ as Oe}from"./index-DShiHdcM.js";import"./vendor-utils-Dgff_Vws.js";import"./vendor-BxkMN6og.js";const je={class:"algo-list"},qe={key:0,class:"breadcrumb"},Ye={class:"folder-path"},He={class:"toolbar"},Je={class:"name-cell"},Ue={key:3,class:"name-text"},We={key:0},Ze={key:0},Qe={style:{display:"flex",gap:"12px"}},Xe=De({__name:"list",setup(et){const H=Ie(),_=m([]),h=m([]),B=m(!1),p=m([]),v=m(0),I=m(""),C=m(null),V=m(""),T=m(!1),K=m(null),J={stock:"Code",multi_factor:"Factor",portfolio:"Portfolio",blank:"Code"},R={stock:`# 股票策略
def initialize(context):
    context.security = '000001'

def handle_data(context, data):
    security = context.security
    price = data[security].close
    ma5 = history(security, 5, 'close')
    if len(ma5) < 5:
        return
    ma_val = ma5.mean()
    if price > ma_val * 1.01 and security not in context.portfolio.positions:
        order_value(security, context.portfolio.available_cash * 0.9)
    elif price < ma_val * 0.99 and security in context.portfolio.positions:
        order_target(security, 0)
`,multi_factor:`# 多因子策略
def initialize(context):
    context.stocks = ['600519', '000858', '601318', '600036', '300750']
    context.rebalance_days = 0

def handle_data(context, data):
    context.rebalance_days += 1
    if context.rebalance_days % 20 != 1:
        return
    target = context.portfolio.total_value / len(context.stocks)
    for code in context.stocks:
        order_target_value(code, target)
`,portfolio:`# 组合策略
def initialize(context):
    context.stocks = ['000001', '600519', '601318']

def handle_data(context, data):
    momentum = {}
    for code in context.stocks:
        h = history(code, 20, 'close')
        if len(h) >= 20 and h.iloc[0] > 0:
            momentum[code] = h.iloc[-1] / h.iloc[0] - 1
    if not momentum:
        return
    best = max(momentum, key=momentum.get)
    for code in list(context.portfolio.positions.keys()):
        if code != best:
            order_target(code, 0)
    if best not in context.portfolio.positions:
        order_value(best, context.portfolio.available_cash * 0.9)
`,blank:`def initialize(context):
    pass

def handle_data(context, data):
    pass
`},w=N(()=>p.value.filter(t=>t.type==="strategy").map(t=>t.id)),U=N(()=>p.value.filter(t=>t.type==="folder").map(t=>t.id)),P=N(()=>{const t=[];if(v.value===0){for(const e of h.value)t.push({...e,rowKey:`folder-${e.id}`});for(const e of _.value.filter(n=>!n.folder_id||n.folder_id===0))t.push({...e,rowKey:`strategy-${e.id}`})}else for(const e of _.value.filter(n=>n.folder_id===v.value))t.push({...e,rowKey:`strategy-${e.id}`});return t});function W(t){return J[t]||"Code"}function Z(t){p.value=t}let g=null;function Q(t,e,n){(e==null?void 0:e.type)!=="selection"&&(C.value||(g&&clearTimeout(g),g=setTimeout(()=>{g=null,ee(t)},200)))}function X(t,e,n){(e==null?void 0:e.type)!=="selection"&&(g&&(clearTimeout(g),g=null),te(t))}function ee(t){if(!C.value){if(t.type==="folder"){v.value=t.id,I.value=t.name,console.log("[list] Enter folder:",t.id,t.name);return}H.push("/algo/edit/"+t.id)}}async function te(t){C.value=t.rowKey,V.value=t.name,await Ke()}function ae(){v.value=0,I.value=""}async function L(t){const e=V.value.trim();if(C.value=null,!(!e||e===t.name))try{t.type==="folder"?await j(t.id,e):await q(t.id,e),r.success("已重命名"),f()}catch{r.error("重命名失败")}}async function f(){B.value=!0;try{const t=await Me(),e=(t==null?void 0:t.data)||t;e!=null&&e.strategies?(_.value=e.strategies,h.value=e.folders||[]):Array.isArray(e)&&(_.value=e,h.value=[]),console.log("[list] loadData:",_.value.length,"strategies,",h.value.length,"folders, currentFolder=",v.value,"root strategies:",_.value.filter(n=>!n.folder_id||n.folder_id===0).length)}finally{B.value=!1}}async function $(t){var a;const n="一个简单的策略-"+(_.value.length+1);try{const i=await Y({name:n,code:R[t]||R.blank,category:t,folder_id:v.value});((i==null?void 0:i.code)??((a=i==null?void 0:i.data)==null?void 0:a.code))===0?(r.success("策略已创建"),await f()):r.error((i==null?void 0:i.msg)||"创建失败")}catch{r.error("创建失败")}}async function G(){var t,e,n;if(!T.value){T.value=!0;try{const a=await Ne();if(((a==null?void 0:a.code)??((t=a==null?void 0:a.data)==null?void 0:t.code))===0){const c=(a==null?void 0:a.msg)||((e=a==null?void 0:a.data)==null?void 0:e.msg)||"模板已同步";r.success(c),await f();return}await f();const i=await Re(),E=Array.isArray(i==null?void 0:i.data)?i.data:Array.isArray(i)?i:[];if(!E.length){r.warning("无可用模板");return}const S=new Set(_.value.map(c=>c.name));let D=0;for(const c of E){if(S.has(c.name))continue;const y=await Y({name:c.name,code:c.code,category:c.category||"stock"});((y==null?void 0:y.code)??((n=y==null?void 0:y.data)==null?void 0:n.code))===0&&(D++,S.add(c.name))}if(D===0){r.info("所有模板已导入");return}r.success("已导入 "+D+" 个示例策略"),await f()}catch{r.error("导入失败")}finally{T.value=!1}}}async function oe(){const{value:t}=await O.prompt("请输入文件夹名称","新建文件夹",{confirmButtonText:"创建",inputValue:"新文件夹",inputPattern:/\S+/}).catch(()=>({value:""}));if(t)try{await Pe(t),r.success("文件夹已创建"),f()}catch{r.error("创建失败")}}async function le(){if(p.value.length!==1){r.warning("请选择一个项目");return}const t=p.value[0],{value:e}=await O.prompt("新名称","重命名",{confirmButtonText:"确定",inputValue:t.name,inputPattern:/\S+/}).catch(()=>({value:""}));if(e)try{t.type==="folder"?await j(t.id,e):await q(t.id,e),r.success("已重命名"),f()}catch{r.error("重命名失败")}}async function ne(t){var e,n;if(w.value.length!==0)try{const a=await Le(w.value,t);if(((a==null?void 0:a.code)??((e=a==null?void 0:a.data)==null?void 0:e.code))!==0){r.error((a==null?void 0:a.msg)||((n=a==null?void 0:a.data)==null?void 0:n.msg)||"移动失败");return}r.success("已移动"),p.value=[],K.value&&K.value.clearSelection(),await f()}catch(a){console.error("moveStrategy error:",a),r.error("移动失败")}}async function ie(){try{w.value.length>0&&await $e(w.value);for(const t of U.value)await Ge(t);r.success("已删除"),f()}catch{r.error("删除失败")}}return Fe(f),(t,e)=>{const n=ve,a=ue,i=be,E=ke,S=fe,D=me,c=he,y=Ee,se=Se,re=_e,de=ye,ce=pe;return u(),x("div",je,[v.value>0?(u(),x("div",qe,[l(a,{text:"",size:"small",onClick:ae},{default:o(()=>[l(n,null,{default:o(()=>[l(A(ge))]),_:1}),e[2]||(e[2]=d(" 返回根目录 ",-1))]),_:1}),z("span",Ye,"/ "+b(I.value),1)])):F("",!0),z("div",He,[l(S,{onCommand:$,trigger:"click"},{dropdown:o(()=>[l(E,null,{default:o(()=>[l(i,{command:"stock"},{default:o(()=>[...e[4]||(e[4]=[d("股票策略",-1)])]),_:1}),l(i,{command:"multi_factor"},{default:o(()=>[...e[5]||(e[5]=[d("多因子策略",-1)])]),_:1}),l(i,{command:"portfolio"},{default:o(()=>[...e[6]||(e[6]=[d("组合策略",-1)])]),_:1}),l(i,{command:"blank"},{default:o(()=>[...e[7]||(e[7]=[d("空白模版",-1)])]),_:1})]),_:1})]),default:o(()=>[l(a,{type:"primary"},{default:o(()=>[...e[3]||(e[3]=[d("+ 新建策略",-1)])]),_:1})]),_:1}),l(a,{onClick:oe},{default:o(()=>[l(n,null,{default:o(()=>[l(A(we))]),_:1}),e[8]||(e[8]=d(" 新建文件夹",-1))]),_:1}),l(a,{disabled:p.value.length===0,onClick:le},{default:o(()=>[...e[9]||(e[9]=[d("重命名",-1)])]),_:1},8,["disabled"]),l(S,{disabled:w.value.length===0,onCommand:ne,trigger:"click"},{dropdown:o(()=>[l(E,null,{default:o(()=>[l(i,{command:0},{default:o(()=>[...e[11]||(e[11]=[d("根目录",-1)])]),_:1}),(u(!0),x(Be,null,Ve(h.value,s=>(u(),k(i,{key:s.id,command:s.id},{default:o(()=>[d(b(s.name),1)]),_:2},1032,["command"]))),128))]),_:1})]),default:o(()=>[l(a,{disabled:w.value.length===0},{default:o(()=>[...e[10]||(e[10]=[d("移动到",-1)])]),_:1},8,["disabled"])]),_:1},8,["disabled"]),l(D,{title:"确定删除选中的项目？",onConfirm:ie,disabled:p.value.length===0},{reference:o(()=>[l(a,{disabled:p.value.length===0,type:"danger",plain:""},{default:o(()=>[l(n,null,{default:o(()=>[l(A(xe))]),_:1}),e[12]||(e[12]=d(" 删除 ",-1))]),_:1},8,["disabled"])]),_:1},8,["disabled"]),l(a,{onClick:G,loading:T.value,style:{"margin-left":"auto"}},{default:o(()=>[...e[13]||(e[13]=[d("导入示例策略",-1)])]),_:1},8,["loading"])]),Ae((u(),k(re,{ref_key:"tableRef",ref:K,data:P.value,onSelectionChange:Z,onRowClick:Q,onRowDblclick:X,stripe:"","row-key":"rowKey",style:{width:"100%"}},{default:o(()=>[l(c,{type:"selection",width:"40"}),l(c,{label:"","min-width":"280"},{default:o(({row:s})=>[z("div",Je,[s.type==="folder"?(u(),k(n,{key:0,size:18,color:"#e6a23c"},{default:o(()=>[l(A(Ce))]),_:1})):(u(),k(n,{key:1,size:18,color:"#409eff"},{default:o(()=>[l(A(Te))]),_:1})),C.value===s.rowKey?(u(),k(y,{key:2,modelValue:V.value,"onUpdate:modelValue":e[0]||(e[0]=M=>V.value=M),size:"small",style:{width:"220px"},onBlur:M=>L(s),onKeyup:ze(M=>L(s),["enter"]),ref:"renameInput"},null,8,["modelValue","onBlur","onKeyup"])):(u(),x("span",Ue,b(s.name),1))])]),_:1}),l(c,{label:"分类",width:"100",align:"center"},{default:o(({row:s})=>[s.type==="strategy"?(u(),k(se,{key:0,size:"small",type:"info",effect:"plain"},{default:o(()=>[d(b(W(s.category)),1)]),_:2},1024)):F("",!0)]),_:1}),l(c,{label:"最后修改时间",width:"180",align:"center"},{default:o(({row:s})=>[d(b(s.updated_at||s.created_at||""),1)]),_:1}),l(c,{label:"历史编译运行",width:"120",align:"center"},{default:o(({row:s})=>[s.type==="strategy"?(u(),x("span",We,b(s.compile_count||0),1)):F("",!0)]),_:1}),l(c,{label:"历史回测",width:"100",align:"center"},{default:o(({row:s})=>[s.type==="strategy"?(u(),x("span",Ze,b(s.backtest_count||0),1)):F("",!0)]),_:1})]),_:1},8,["data"])),[[ce,B.value]]),!B.value&&P.value.length===0?(u(),k(de,{key:1,description:"还没有策略，点击「新建策略」或导入示例策略"},{default:o(()=>[z("div",Qe,[l(a,{type:"primary",onClick:e[1]||(e[1]=s=>$("stock"))},{default:o(()=>[...e[14]||(e[14]=[d("新建股票策略",-1)])]),_:1}),l(a,{onClick:G,loading:T.value},{default:o(()=>[...e[15]||(e[15]=[d("导入示例策略",-1)])]),_:1},8,["loading"])])]),_:1})):F("",!0)])}}}),st=Oe(Xe,[["__scopeId","data-v-06fd55c7"]]);export{st as default};
