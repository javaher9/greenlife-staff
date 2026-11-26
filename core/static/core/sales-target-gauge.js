/* Same polar/arc/needle construction used by the executive targets page.
   Receives only percentages: never inserts sales amounts into the DOM. */
(function(){
  const meters=document.querySelectorAll(".care-target-widget .care-target-meter");
  if(!meters.length)return;
  const ns="http://www.w3.org/2000/svg";
  function elem(tag,attrs,content){
    const el=document.createElementNS(ns,tag);
    Object.entries(attrs||{}).forEach(([k,v])=>el.setAttribute(k,v));
    if(content!=null)el.textContent=content;
    return el;
  }
  function polar(deg,r){return [110+r*Math.cos(deg*Math.PI/180),111+r*Math.sin(deg*Math.PI/180)];}
  function arc(a,b,r){
    const [x1,y1]=polar(a,r),[x2,y2]=polar(b,r);
    return "M "+x1.toFixed(2)+" "+y1.toFixed(2)+" A "+r+" "+r+" 0 "+(b-a>180?1:0)+" 1 "+x2.toFixed(2)+" "+y2.toFixed(2);
  }
  const colors=["#fc4768","#f5bc31","#1fd8a5","#2caeff","#a96bfa"];
  meters.forEach(box=>{
    const parsePercent=(raw)=>{
      const normalized=String(raw??"").trim()
        .replace(/[۰-۹]/g,ch=>String(ch.charCodeAt(0)-1776))
        .replace(/[٠-٩]/g,ch=>String(ch.charCodeAt(0)-1632))
        .replace(/٫/g,".").replace(/٬/g,"").replace(",",".");
      return Number(normalized);
    };
    const value=Math.max(0,parsePercent(box.dataset.percent)||0);
    const t=["heavy","floor","one","two"].map(k=>parsePercent(box.dataset[k]));
    const ready=t.every(Number.isFinite)&&t[0]>0&&t[0]<t[1]&&t[1]<t[2]&&t[3]>t[2];
    const svg=elem("svg",{viewBox:"0 15 220 180",role:"img","aria-label":box.getAttribute("aria-label")||"درصد تحقق تارگت"});
    const unit=box.closest(".care-target-unit");
    const title=unit.querySelector(".care-target-title").textContent.trim();
    const state=unit.querySelector(".care-target-state");
    const stateColors={red:"#bd334e",yellow:"#94600d",green:"#187550",blue:"#176ea6",purple:"#7850ae"};
    const stateKey=Object.keys(stateColors).find(key=>state.classList.contains("mt-"+key));
    const statusOnly = box.hasAttribute("data-status-only");
    function labels(){
      svg.appendChild(elem("text",{x:110,y:79,fill:"#4d7168","font-size":17,"text-anchor":"middle","font-family":"Tahoma,Arial","font-weight":"bold"},title));
      if (!statusOnly) {
        svg.appendChild(elem("text",{x:110,y:116,fill:"#244f49","font-size":29,"text-anchor":"middle","font-family":"Arial,Tahoma","font-weight":"bold"},Math.round(value)+"%"));
      }
      svg.appendChild(elem("text",{x:110,y:statusOnly?116:143,fill:stateColors[stateKey]||"#4d7168","font-size":statusOnly?19:15,"text-anchor":"middle","font-family":"Tahoma,Arial","font-weight":"bold"},state.textContent.trim()));
    }
    function render() {
      labels();
      box.textContent = "";
      box.appendChild(svg);
      unit.classList.add("target-gauge-rendered");
    }
    if(!ready){render();return;}
    const upper=Math.max(1.2*t[3],value);
    const edges=[0,...t,upper];
    for(let i=0;i<5;i++){
      const a=130+280*edges[i]/upper,b=130+280*edges[i+1]/upper;
      const gap=Math.min(.72,(b-a)/8);
      if(b-a>1.5)svg.appendChild(elem("path",{d:arc(a+gap,b-gap,78),fill:"none",stroke:colors[i],"stroke-width":22,"stroke-linecap":"butt"}));
    }
    const angle=130+280*Math.min(value/upper,1);
    const [px,py]=polar(angle,84),[mx,my]=polar(angle,40);
    svg.appendChild(elem("path",{d:"M "+mx+" "+my+" L "+px+" "+py,stroke:"#edfaff","stroke-width":7.5,"stroke-linecap":"round",fill:"none"}));
    svg.appendChild(elem("circle",{cx:px,cy:py,r:9,fill:"#12354c",stroke:"#edfaff","stroke-width":4}));
    render();
  });
})();
