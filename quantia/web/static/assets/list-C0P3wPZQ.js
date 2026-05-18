import{d as fe,o as me,c as h,f as B,e as N,D as pe,g as b,l as p,k as l,w as o,r as f,t as w,q as M,G as _e,j as u,n as d,h as K,L as ye,M as ve,F as ge,v as ke,N as be,O as we,P as xe,m as he,E as r,b as Ce,K as j,I as Se,_ as Te}from"./index-Da_vS4bt.js";import{c as Fe,r as Y,e as q,s as U,f as De,h as Ae,i as Be,m as Ke,j as ze,k as Ee}from"./stock-B1l6LoDz.js";const Ne={class:"algo-list"},Ve={key:0,class:"breadcrumb"},Re={class:"folder-path"},Ie={class:"toolbar"},Me={class:"name-cell"},Pe={key:3,class:"name-text"},$e={key:0},Le={key:0},Ge={style:{display:"flex",gap:"12px"}},Oe=fe({__name:"list",setup(je){const H=Ce(),y=p([]),C=p([]),z=p(!1),_=p([]),g=p(0),V=p(""),S=p(null),E=p(""),T=p(!1),R=p(null),J={stock:"Code",multi_factor:"Factor",portfolio:"Portfolio",blank:"Code"},P={stock:`# 股票策略
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
`},x=M(()=>_.value.filter(t=>t.type==="strategy").map(t=>t.id)),Q=M(()=>_.value.filter(t=>t.type==="folder").map(t=>t.id)),$=M(()=>{const t=[];if(g.value===0){for(const e of C.value)t.push({...e,rowKey:`folder-${e.id}`});for(const e of y.value.filter(n=>!n.folder_id||n.folder_id===0))t.push({...e,rowKey:`strategy-${e.id}`})}else for(const e of y.value.filter(n=>n.folder_id===g.value))t.push({...e,rowKey:`strategy-${e.id}`});return t});function W(t){return J[t]||"Code"}function X(t){_.value=t}let k=null;function Z(t,e,n){(e==null?void 0:e.type)!=="selection"&&(S.value||(k&&clearTimeout(k),k=setTimeout(()=>{k=null,te(t)},200)))}function ee(t,e,n){(e==null?void 0:e.type)!=="selection"&&(k&&(clearTimeout(k),k=null),ae(t))}function te(t){if(!S.value){if(t.type==="folder"){g.value=t.id,V.value=t.name,console.log("[list] Enter folder:",t.id,t.name);return}H.push("/algo/edit/"+t.id)}}async function ae(t){S.value=t.rowKey,E.value=t.name,await Se()}function oe(){g.value=0,V.value=""}async function L(t){const e=E.value.trim();if(S.value=null,!(!e||e===t.name))try{t.type==="folder"?await Y(t.id,e):await q(t.id,e),r.success("已重命名"),m()}catch{r.error("重命名失败")}}async function m(){z.value=!0;try{const t=await Fe(),e=(t==null?void 0:t.data)||t;e!=null&&e.strategies?(y.value=e.strategies,C.value=e.folders||[]):Array.isArray(e)&&(y.value=e,C.value=[]),console.log("[list] loadData:",y.value.length,"strategies,",C.value.length,"folders, currentFolder=",g.value,"root strategies:",y.value.filter(n=>!n.folder_id||n.folder_id===0).length)}finally{z.value=!1}}async function G(t){var a;const n="一个简单的策略-"+(y.value.length+1);try{const i=await U({name:n,code:P[t]||P.blank,category:t,folder_id:g.value});((i==null?void 0:i.code)??((a=i==null?void 0:i.data)==null?void 0:a.code))===0?(r.success("策略已创建"),await m()):r.error((i==null?void 0:i.msg)||"创建失败")}catch{r.error("创建失败")}}async function O(){var t,e,n;if(!T.value){T.value=!0;try{const a=await De();if(((a==null?void 0:a.code)??((t=a==null?void 0:a.data)==null?void 0:t.code))===0){const c=(a==null?void 0:a.msg)||((e=a==null?void 0:a.data)==null?void 0:e.msg)||"模板已同步";r.success(c),await m();return}await m();const i=await Ae(),F=Array.isArray(i==null?void 0:i.data)?i.data:Array.isArray(i)?i:[];if(!F.length){r.warning("无可用模板");return}const D=new Set(y.value.map(c=>c.name));let A=0;for(const c of F){if(D.has(c.name))continue;const v=await U({name:c.name,code:c.code,category:c.category||"stock"});((v==null?void 0:v.code)??((n=v==null?void 0:v.data)==null?void 0:n.code))===0&&(A++,D.add(c.name))}if(A===0){r.info("所有模板已导入");return}r.success("已导入 "+A+" 个示例策略"),await m()}catch{r.error("导入失败")}finally{T.value=!1}}}async function le(){const{value:t}=await j.prompt("请输入文件夹名称","新建文件夹",{confirmButtonText:"创建",inputValue:"新文件夹",inputPattern:/\S+/}).catch(()=>({value:""}));if(t)try{await Be(t),r.success("文件夹已创建"),m()}catch{r.error("创建失败")}}async function ne(){if(_.value.length!==1){r.warning("请选择一个项目");return}const t=_.value[0],{value:e}=await j.prompt("新名称","重命名",{confirmButtonText:"确定",inputValue:t.name,inputPattern:/\S+/}).catch(()=>({value:""}));if(e)try{t.type==="folder"?await Y(t.id,e):await q(t.id,e),r.success("已重命名"),m()}catch{r.error("重命名失败")}}async function ie(t){var e,n;if(x.value.length!==0)try{const a=await Ke(x.value,t);if(((a==null?void 0:a.code)??((e=a==null?void 0:a.data)==null?void 0:e.code))!==0){r.error((a==null?void 0:a.msg)||((n=a==null?void 0:a.data)==null?void 0:n.msg)||"移动失败");return}r.success("已移动"),_.value=[],R.value&&R.value.clearSelection(),await m()}catch(a){console.error("moveStrategy error:",a),r.error("移动失败")}}async function se(){try{x.value.length>0&&await ze(x.value);for(const t of Q.value)await Ee(t);r.success("已删除"),m()}catch{r.error("删除失败")}}return me(m),(t,e)=>{const n=f("el-icon"),a=f("el-button"),i=f("el-dropdown-item"),F=f("el-dropdown-menu"),D=f("el-dropdown"),A=f("el-popconfirm"),c=f("el-table-column"),v=f("el-input"),re=f("el-tag"),de=f("el-table"),ce=f("el-empty"),ue=_e("loading");return u(),h("div",Ne,[g.value>0?(u(),h("div",Ve,[l(a,{text:"",size:"small",onClick:oe},{default:o(()=>[l(n,null,{default:o(()=>[l(K(ye))]),_:1}),e[2]||(e[2]=d(" 返回根目录 ",-1))]),_:1}),N("span",Re,"/ "+w(V.value),1)])):B("",!0),N("div",Ie,[l(D,{onCommand:G,trigger:"click"},{dropdown:o(()=>[l(F,null,{default:o(()=>[l(i,{command:"stock"},{default:o(()=>[...e[4]||(e[4]=[d("股票策略",-1)])]),_:1}),l(i,{command:"multi_factor"},{default:o(()=>[...e[5]||(e[5]=[d("多因子策略",-1)])]),_:1}),l(i,{command:"portfolio"},{default:o(()=>[...e[6]||(e[6]=[d("组合策略",-1)])]),_:1}),l(i,{command:"blank"},{default:o(()=>[...e[7]||(e[7]=[d("空白模版",-1)])]),_:1})]),_:1})]),default:o(()=>[l(a,{type:"primary"},{default:o(()=>[...e[3]||(e[3]=[d("+ 新建策略",-1)])]),_:1})]),_:1}),l(a,{onClick:le},{default:o(()=>[l(n,null,{default:o(()=>[l(K(ve))]),_:1}),e[8]||(e[8]=d(" 新建文件夹",-1))]),_:1}),l(a,{disabled:_.value.length===0,onClick:ne},{default:o(()=>[...e[9]||(e[9]=[d("重命名",-1)])]),_:1},8,["disabled"]),l(D,{disabled:x.value.length===0,onCommand:ie,trigger:"click"},{dropdown:o(()=>[l(F,null,{default:o(()=>[l(i,{command:0},{default:o(()=>[...e[11]||(e[11]=[d("根目录",-1)])]),_:1}),(u(!0),h(ge,null,ke(C.value,s=>(u(),b(i,{key:s.id,command:s.id},{default:o(()=>[d(w(s.name),1)]),_:2},1032,["command"]))),128))]),_:1})]),default:o(()=>[l(a,{disabled:x.value.length===0},{default:o(()=>[...e[10]||(e[10]=[d("移动到",-1)])]),_:1},8,["disabled"])]),_:1},8,["disabled"]),l(A,{title:"确定删除选中的项目？",onConfirm:se,disabled:_.value.length===0},{reference:o(()=>[l(a,{disabled:_.value.length===0,type:"danger",plain:""},{default:o(()=>[l(n,null,{default:o(()=>[l(K(be))]),_:1}),e[12]||(e[12]=d(" 删除 ",-1))]),_:1},8,["disabled"])]),_:1},8,["disabled"]),l(a,{onClick:O,loading:T.value,style:{"margin-left":"auto"}},{default:o(()=>[...e[13]||(e[13]=[d("导入示例策略",-1)])]),_:1},8,["loading"])]),pe((u(),b(de,{ref_key:"tableRef",ref:R,data:$.value,onSelectionChange:X,onRowClick:Z,onRowDblclick:ee,stripe:"","row-key":"rowKey",style:{width:"100%"}},{default:o(()=>[l(c,{type:"selection",width:"40"}),l(c,{label:"","min-width":"280"},{default:o(({row:s})=>[N("div",Me,[s.type==="folder"?(u(),b(n,{key:0,size:18,color:"#e6a23c"},{default:o(()=>[l(K(we))]),_:1})):(u(),b(n,{key:1,size:18,color:"#409eff"},{default:o(()=>[l(K(xe))]),_:1})),S.value===s.rowKey?(u(),b(v,{key:2,modelValue:E.value,"onUpdate:modelValue":e[0]||(e[0]=I=>E.value=I),size:"small",style:{width:"220px"},onBlur:I=>L(s),onKeyup:he(I=>L(s),["enter"]),ref:"renameInput"},null,8,["modelValue","onBlur","onKeyup"])):(u(),h("span",Pe,w(s.name),1))])]),_:1}),l(c,{label:"分类",width:"100",align:"center"},{default:o(({row:s})=>[s.type==="strategy"?(u(),b(re,{key:0,size:"small",type:"info",effect:"plain"},{default:o(()=>[d(w(W(s.category)),1)]),_:2},1024)):B("",!0)]),_:1}),l(c,{label:"最后修改时间",width:"180",align:"center"},{default:o(({row:s})=>[d(w(s.updated_at||s.created_at||""),1)]),_:1}),l(c,{label:"历史编译运行",width:"120",align:"center"},{default:o(({row:s})=>[s.type==="strategy"?(u(),h("span",$e,w(s.compile_count||0),1)):B("",!0)]),_:1}),l(c,{label:"历史回测",width:"100",align:"center"},{default:o(({row:s})=>[s.type==="strategy"?(u(),h("span",Le,w(s.backtest_count||0),1)):B("",!0)]),_:1})]),_:1},8,["data"])),[[ue,z.value]]),!z.value&&$.value.length===0?(u(),b(ce,{key:1,description:"还没有策略，点击「新建策略」或导入示例策略"},{default:o(()=>[N("div",Ge,[l(a,{type:"primary",onClick:e[1]||(e[1]=s=>G("stock"))},{default:o(()=>[...e[14]||(e[14]=[d("新建股票策略",-1)])]),_:1}),l(a,{onClick:O,loading:T.value},{default:o(()=>[...e[15]||(e[15]=[d("导入示例策略",-1)])]),_:1},8,["loading"])])]),_:1})):B("",!0)])}}}),Ue=Te(Oe,[["__scopeId","data-v-35967c99"]]);export{Ue as default};
