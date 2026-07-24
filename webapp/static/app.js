const tg=window.Telegram?.WebApp;try{tg?.ready();tg?.expand();tg?.disableClosingConfirmation?.();}catch(_){}
const API='';
const State={telegramId:null,user:null,plans:[],goals:[],habits:[],habitModal:{id:null},habitIcon:'🏃',habitFreq:'daily',habitDur:'permanent',habitWeekdays:[],habitRem:'off',habitView:'today',trackerWeekStart:null,statsView:'mine',lbPeriod:'all',goalPeriod:'yearly',selectedDate:new Date(),selectedYear:new Date().getFullYear(),selectedMonth:new Date().getMonth(),modal:{period:'yearly',periodKey:null,id:null},planModal:{id:null},plansRange:[],theme:localStorage.getItem('iz_theme')||'default',mode:localStorage.getItem('iz_mode')||'light',
  // Do'stlar (Friends) moduli
  friendsView:'list',       // 'list' | 'group' | 'member'
  groups:[],
  currentGroup:null,        // {id,name,description,invite_code,is_owner,members:[...]}
  currentMember:null,       // {member:{...}, plans:[...], habits:[...], goals:[...], can_manage}
  // Boshqa a'zo uchun reja/maqsad/odat yaratayotganda o'z modallari (plan/habit/goal)
  // qayta ishlatiladi (barcha maydonlar bilan). Bu maydon set bo'lsa, save
  // handlerlar item'ni friends API orqali TARGET a'zoning hisobiga yozadi.
  forMemberContext:null,    // {groupId, userId, name} yoki null
  // Global app konfiguratsiyasi (admin panelidan boshqariladigan bayroqlar).
  // `/api/webapp/config` dan yuklanadi. Yuklanmagunicha default TRUE
  // (Ruxsatlar tugmasi ko'rinadi) — aks holda birinchi renderda "flash"
  // ko'rinishi mumkin.
  appConfig:{group_perms_menu_enabled:true},
};

const UZ_MONTHS=['Yanvar','Fevral','Mart','Aprel','May','Iyun','Iyul','Avgust','Sentabr','Oktabr','Noyabr','Dekabr'];
const UZ_MONTHS_SHORT=['Yan','Fev','Mar','Apr','May','Iyn','Iyl','Avg','Sen','Okt','Noy','Dek'];
const UZ_DOW_SHORT=['Du','Se','Cho','Pa','Ju','Sha','Ya'];
const UZ_DOW_FULL=['Dushanba','Seshanba','Chorshanba','Payshanba','Juma','Shanba','Yakshanba'];

const pad=n=>n<10?'0'+n:''+n;
const ymd=d=>d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate());
function isoWeek(d){const dt=new Date(Date.UTC(d.getFullYear(),d.getMonth(),d.getDate()));const dn=dt.getUTCDay()||7;dt.setUTCDate(dt.getUTCDate()+4-dn);const ys=new Date(Date.UTC(dt.getUTCFullYear(),0,1));return{year:dt.getUTCFullYear(),week:Math.ceil((((dt-ys)/86400000)+1)/7)};}
const weekKey=d=>{const w=isoWeek(d);return w.year+'-W'+pad(w.week);};
function startOfWeek(d){const x=new Date(d);const dy=x.getDay();const df=dy===0?-6:1-dy;x.setDate(x.getDate()+df);x.setHours(0,0,0,0);return x;}
function endOfWeek(d){const s=startOfWeek(d);const e=new Date(s);e.setDate(s.getDate()+6);return e;}
function addDays(d,n){const x=new Date(d);x.setDate(x.getDate()+n);return x;}
const formatDateLong=d=>UZ_DOW_FULL[(d.getDay()+6)%7]+', '+d.getDate()+' '+UZ_MONTHS_SHORT[d.getMonth()].toLowerCase();
const formatRange=(a,b)=>a.getMonth()===b.getMonth()?a.getDate()+'–'+b.getDate()+' '+UZ_MONTHS_SHORT[a.getMonth()]:a.getDate()+' '+UZ_MONTHS_SHORT[a.getMonth()]+' – '+b.getDate()+' '+UZ_MONTHS_SHORT[b.getMonth()];

function applyUserName(nm){
  nm=(nm||'Foydalanuvchi').trim()||'Foydalanuvchi';
  if(State.user)State.user.first_name=nm;
  State.displayName=nm;
  const ini=(nm[0]||'A').toUpperCase();
  setText('userName',nm);setText('profName',nm);
  const hav=document.getElementById('hdrAv');const pav=document.getElementById('profAv');
  // Profil rasmi (Telegram bergan bo'lsa) — bo'lmasa ism birinchi harfi
  const photo=State.photoUrl;
  if(hav){if(photo){hav.style.backgroundImage='url("'+photo+'")';hav.textContent='';}else{hav.style.backgroundImage='';hav.textContent=ini;}}
  if(pav){if(photo){pav.style.backgroundImage='url("'+photo+'")';pav.style.backgroundSize='cover';pav.style.backgroundPosition='center';pav.textContent='';}else{pav.style.backgroundImage='';pav.textContent=ini;}}
  const dsc=document.getElementById('editNameDsc');if(dsc)dsc.textContent='Joriy: '+nm;
}
function initUser(){const u=tg?.initDataUnsafe?.user;if(u){State.telegramId=u.id;State.user=u;State.photoUrl=u.photo_url||null;}else{State.telegramId=parseInt(localStorage.getItem('iz_demo_id')||'12345',10);State.user={id:State.telegramId,first_name:'Foydalanuvchi',username:'demo'};State.photoUrl=null;}
const nm=State.user.first_name||'Foydalanuvchi';
applyUserName(nm);
document.getElementById('profUn').textContent=State.user.username?'@'+State.user.username:'';document.getElementById('todayDate').textContent=formatDateLong(new Date());}

// Global API wrapper.
// 402 (Payment Required) — Backend endi barcha "Premium kerak" holatlarda
// 402 qaytaradi. Bu yerda global tanib olamiz va foydalanuvchiga inline
// Premium dialog'ni ochamiz — chaqiruvchi kod alohida 402 tekshiruvi
// yozmasa ham UI xatti-harakati bir xil bo'ladi. `opts.skipPremiumDialog`
// (true) berilgan bo'lsa chaqiruvchi o'zi tanish qiladi.
async function api(path,opts={}){
  const url=API+path+(path.includes('?')?'&':'?')+'telegram_id='+State.telegramId;
  const headers={'Content-Type':'application/json',...(opts.headers||{})};
  try{if(tg&&tg.initData)headers['X-Telegram-Init-Data']=tg.initData;}catch(_){}
  const res=await fetch(url,{headers,...opts});
  if(!res.ok){
    if(res.status===402 && !opts.skipPremiumDialog){
      // Server javobidan xato matnini olishga urinamiz — dialog message uchun.
      let detail='';
      try{const j=await res.clone().json();detail=(j&&j.detail)?String(j.detail):'';}catch(_){}
      // Standart Premium dialog. Chaqiruvchi kod baribir throw ushlaydi.
      try{
        premiumRequiredDialog({
          icon:'💎',
          title:'Faqat Premium foydalanuvchilar uchun',
          message:detail||'Bu amal Premium foydalanuvchilar uchun.',
        });
      }catch(_){}
    }
    throw new Error('API '+res.status);
  }
  return res.json();
}

async function loadPlansAPI(){try{const d=await api('/api/webapp/plans');State.plans=d.plans||[];if(d.user){State.user={...State.user,...d.user};if(d.user.full_name)applyUserName(d.user.full_name);setText('streakCount',d.user.streak||0);setText('msScore',d.user.total_score||0);setText('stStreak',d.user.streak||0);setText('stTotal',d.user.total_score||0);setText('pfStreak',d.user.streak||0);setText('pfScore',d.user.total_score||0);}setText('msPlans',State.plans.length);renderDayStrip();renderPlans();renderHero();updateHomePlansTitle();loadHomeHabits();}catch(e){console.warn('plans',e);State.plans=[];renderPlans();}}

// Tanlangan kun uchun rejalarni yuklash (bugun yoki o'tgan/kelajak kun)
function isSameDay(ymdStr,dateObj){try{return ymdStr===ymd(dateObj||new Date());}catch(_){return false;}}
async function loadPlansForSelectedDay(){
  const day=ymd(State.selectedDate||new Date());
  try{
    const d=await api('/api/webapp/plans?date_from='+day+'&date_to='+day);
    State.plans=d.plans||[];
  }catch(e){console.warn('day plans',e);State.plans=[];}
  setText('msPlans',State.plans.length);
  renderDayStrip();renderPlans();updateHomePlansTitle();
}
function updateHomePlansTitle(){
  const sel=State.selectedDate||new Date();
  const todayStr=ymd(new Date());
  const selStr=ymd(sel);
  let label;
  if(selStr===todayStr)label='Bugungi rejalar';
  else if(selStr===ymd(addDays(new Date(),1)))label='Ertangi rejalar';
  else if(selStr===ymd(addDays(new Date(),-1)))label='Kechagi rejalar';
  else label=sel.getDate()+' '+UZ_MONTHS_SHORT[sel.getMonth()]+' rejalari';
  setText('homePlansTitle',label);
}
function renderDayStrip(){
  const strip=document.getElementById('dayStrip');if(!strip)return;
  const sel=ymd(State.selectedDate||new Date());
  const todayStr=ymd(new Date());
  // Xronologik tartib: o'tgan 14 kun ... BUGUN ... kelgusi 30 kun.
  // Foydalanuvchi ertangi va undan keyingi kunlarni ham ko'ra oladi va
  // ular uchun reja yarata oladi (plan modali sana tanlashni beradi).
  let html='';
  for(let off=-14;off<=30;off++){
    const d=addDays(new Date(),off);
    const k=ymd(d);
    const isToday=k===todayStr;
    const isSel=k===sel;
    const dw=UZ_DOW_SHORT[(d.getDay()+6)%7];
    html+=`<div class="day-chip ${isSel?'active':''} ${isToday?'today':''}" data-day="${k}"><div class="dw">${isToday?'Bugun':dw}</div><div class="dd">${d.getDate()}</div><div class="dm">${UZ_MONTHS_SHORT[d.getMonth()]}</div></div>`;
  }
  strip.innerHTML=html;
  strip.querySelectorAll('.day-chip').forEach(c=>c.onclick=()=>{State.selectedDate=new Date(c.dataset.day+'T00:00:00');loadPlansForSelectedDay();});
  // Tanlangan (yoki bugungi) chipni AYNAN o'rtaga keltiramiz
  requestAnimationFrame(()=>{
    const act=strip.querySelector('.day-chip.active')||strip.querySelector('.day-chip.today');
    if(act){const target=act.offsetLeft-(strip.clientWidth/2)+(act.offsetWidth/2);strip.scrollTo({left:Math.max(0,target),behavior:'auto'});}
  });
}async function loadGoalsAPI(){try{State.goals=await api('/api/webapp/goals');}catch(e){console.warn('goals',e);State.goals=[];}setText('msGoals',State.goals.length);setText('stGoals',State.goals.filter(g=>!g.completed).length);const done=State.goals.filter(g=>g.completed).length+State.plans.filter(p=>p.status==='done').length;setText('stDone',done);setText('pfDone',done);renderGoalsView();}

async function loadPlansRange(){try{const tod=new Date();const df=ymd(addDays(tod,-29));const dt=ymd(tod);const d=await api('/api/webapp/plans?date_from='+df+'&date_to='+dt);State.plansRange=d.plans||[];}catch(e){console.warn('range',e);State.plansRange=State.plans;}}

const apiGoalCreate=p=>api('/api/webapp/goals',{method:'POST',body:JSON.stringify(p)});
const apiGoalUpdate=(id,p)=>api('/api/webapp/goals/'+id,{method:'PUT',body:JSON.stringify(p)});
const apiGoalDelete=id=>api('/api/webapp/goals/'+id,{method:'DELETE'});

// ── Do'stlar (Friends) API helperlar ─────────────────────────
const apiGroupsList = ()=>api('/api/webapp/friends/groups');
const apiGroupCreate = (name,description)=>api('/api/webapp/friends/groups',{method:'POST',body:JSON.stringify({name,description:description||null})});
const apiGroupGet = (id)=>api('/api/webapp/friends/groups/'+id);
const apiGroupPatch = (id,body)=>api('/api/webapp/friends/groups/'+id,{method:'PATCH',body:JSON.stringify(body)});
const apiGroupDelete = (id)=>api('/api/webapp/friends/groups/'+id,{method:'DELETE'});
const apiGroupLeave = (id)=>api('/api/webapp/friends/groups/'+id+'/leave',{method:'POST'});
const apiGroupJoin = (code)=>api('/api/webapp/friends/join/'+encodeURIComponent(code),{method:'POST'});
const apiMemberView = (gid,uid,dateStr)=>api('/api/webapp/friends/groups/'+gid+'/members/'+uid+(dateStr?('?date='+encodeURIComponent(dateStr)):''));
const apiPerms = (gid)=>api('/api/webapp/friends/groups/'+gid+'/permissions');
// Ruxsatni yangilash — ikkala bayroq ham ixtiyoriy. Backend can_manage=True
// bo'lsa can_view'ni avtomatik True qulflaydi.
const apiPermsSet = (gid,granteeId,body)=>api('/api/webapp/friends/groups/'+gid+'/permissions/'+granteeId,{method:'PUT',body:JSON.stringify(body||{})});
// Ega tomonidan guruhdan a'zoni chiqarib yuborish
const apiRemoveMember = (gid,uid)=>api('/api/webapp/friends/groups/'+gid+'/members/'+uid,{method:'DELETE'});
// Ega tomonidan a'zoni "pauza" qilish yoki qayta yoqish (is_active).
// FALSE bo'lsa a'zoning ma'lumotlari boshqalarga ko'rinmaydi va Telegram
// hisobotlarida umuman hisoblanmaydi.
const apiSetMemberActive = (gid,uid,active)=>api('/api/webapp/friends/groups/'+gid+'/members/'+uid+'/active',{method:'PUT',body:JSON.stringify({is_active:!!active})});
const apiForMemberPlan = (gid,uid,body)=>api('/api/webapp/friends/groups/'+gid+'/members/'+uid+'/plans',{method:'POST',body:JSON.stringify(body)});
// Eslatma: apiForMemberGoal olib tashlandi — a'zolar bir-biriga maqsad qo'sha
// olmaydi (foydalanuvchi talabiga muvofiq). Faqat reja va odat qoldi.
const apiForMemberHabit = (gid,uid,body)=>api('/api/webapp/friends/groups/'+gid+'/members/'+uid+'/habits',{method:'POST',body:JSON.stringify(body)});
// Telegram digest/plans sozlamalari (faqat guruh egasi)
const apiDigestSettings = (gid)=>api('/api/webapp/friends/groups/'+gid+'/telegram/settings');
const apiDigestCandidates = (gid)=>api('/api/webapp/friends/groups/'+gid+'/telegram/candidates');
const apiDigestUpdate = (gid,body)=>api('/api/webapp/friends/groups/'+gid+'/telegram/settings',{method:'PUT',body:JSON.stringify(body||{})});
const apiDigestLink = (gid,chatId,chatTitle)=>api('/api/webapp/friends/groups/'+gid+'/telegram/link',{method:'POST',body:JSON.stringify({telegram_chat_id:chatId,telegram_chat_title:chatTitle||null})});
const apiDigestUnlink = (gid)=>api('/api/webapp/friends/groups/'+gid+'/telegram/unlink',{method:'POST'});
// Yangi: ikki alohida test yuborish endpoint'lari (per-user rejalar/hisobot)
const apiPlansTest = (gid)=>api('/api/webapp/friends/groups/'+gid+'/telegram/plans-test',{method:'POST'});
const apiReportTest = (gid)=>api('/api/webapp/friends/groups/'+gid+'/telegram/report-test',{method:'POST'});
// Eslatma: eski `apiDigestTest` (/telegram/test) endi mavjud emas — o'rniga
// apiPlansTest va apiReportTest ishlatiladi (yuqorida).
const apiPlanCreate=p=>api('/api/webapp/plans',{method:'POST',body:JSON.stringify(p)});
const apiPlanUpdate=(id,p)=>api('/api/webapp/plans/'+id,{method:'PUT',body:JSON.stringify(p)});
const apiPlanDelete=id=>api('/api/webapp/plans/'+id,{method:'DELETE'});

// ── Odatlar (habits) API ────────────────────────────────────────────────
const apiHabitCreate=p=>api('/api/webapp/habits',{method:'POST',body:JSON.stringify(p)});
const apiHabitUpdate=(id,p)=>api('/api/webapp/habits/'+id,{method:'PUT',body:JSON.stringify(p)});
const apiHabitDelete=id=>api('/api/webapp/habits/'+id,{method:'DELETE'});
const apiHabitToggle=(id,done,date)=>api('/api/webapp/habits/'+id+'/toggle',{method:'POST',body:JSON.stringify({done:done,date:date||null})});
const apiProfileUpdate=(name,notif,photo)=>{const b={};if(name!=null)b.full_name=name;if(notif!=null)b.notifications_enabled=notif;if(photo!=null)b.photo_url=photo;return api('/api/webapp/profile',{method:'PUT',body:JSON.stringify(b)});};
function openTgLink(u){try{if(tg&&tg.openTelegramLink)tg.openTelegramLink(u);else window.open(u,'_blank');}catch(_){try{window.open(u,'_blank');}catch(__){}}}
// ── Global konfiguratsiya (admin bayroqlari) ─────────────────────────────
// `/api/webapp/config` admin panelidan boshqariladigan global bayroqlarni
// qaytaradi (masalan Do'stlar sahifasidagi "🛡 Ruxsatlar" tugmasi
// yoqilganmi). Bu funksiya ilovaning boshida bir marta chaqiriladi va
// natija State.appConfig'ga yoziladi; DOM elementlarini `_applyAppConfig`
// yashirib/ko'rsatadi. Xato bo'lsa jim o'tamiz — default (yoqilgan) qoladi.
async function loadAppConfig(){
  try{
    const c=await api('/api/webapp/config');
    if(c&&typeof c==='object'){
      State.appConfig={
        group_perms_menu_enabled:c.group_perms_menu_enabled!==false,
      };
    }
  }catch(_){/* jim: default holat qoladi */}
  _applyAppConfig();
}

// Bayroqlar asosida DOM elementlarini yangilaydi.
// Hozircha bo'sh (foydalanuvchi so'roviga muvofiq: "🛡 Ruxsatlar" tugmasi
// har doim ko'rinadi — admin toggle olib tashlandi). Kelajakda yangi bayroqlar
// qo'shilsa shu yerda qo'llaniladi.
function _applyAppConfig(){
  // no-op: hozircha DOM'ga hech qanday ta'sir yo'q.
}

async function loadProfileMeta(){try{const p=await api('/api/webapp/profile');State.profile=p;if(p&&p.full_name)applyUserName(p.full_name);const sd=document.getElementById('shareDesc');if(sd){const c=p.referral_count||0;sd.textContent=c>0?(c+' faol do\'st taklif qilingan · davom eting'):'Do\'stingiz birinchi rejasini bajarsa — unga 3 kun, sizga har 5 faol do\'stga 7 kun';}}catch(_){}}

// ── Do'stni taklif qilish (ulashish) ────────────────────────────────────
// Bot va Mini App bir xil xabarni ulashadi (foydalanuvchi bir xil natija ko'radi):
// reklama matni + botga olib boradigan shaxsiy deep-link.
const REFERRAL_SHARE_TEXT=[
  "Siz Intizomlimisiz ⁉️",
  "",
  "📚 Kitob o'qish bilim beradi.",
  "",
  "💡Lekin bilimni natijaga aylantiradigan narsa — intizom.",
  "",
  "Ko'pchilik:",
  "❌ Maqsad qo'yadi",
  "❌ Reja tuzadi",
  "❌ Lekin oxirigacha yetib bormaydi",
  "",
  "⌛️ IntizomAi esa sizning maqsadlaringiz, rejalaringiz va odatlaringizni kuzatib boradi.",
  "",
  "🧠 AI vaqt o'tishi bilan sizni o'rganadi:",
  "✅ Progressingizni kuzatadi",
  "✅ Odatlaringizni tahlil qiladi",
  "✅ Sizga mos tavsiyalar beradi",
  "",
  "📊 Statistika",
  "⚡️ Maqsadlar",
  "⌛️ Eslatmalar",
  "🤖 AI mentor",
  "",
  "🌐 Hammasi bitta qulay Web App ichida.",
  "",
  "⭐️ Bilim + Intizom = Natija"
].join("\n");

function shareInvite(){
  const link=State.profile&&State.profile.referral_link;
  if(!link){toast('Havola tayyorlanmoqda…');return;}
  // Telegram share URL — foydalanuvchi kimlarga forward qilishni tanlaydi.
  const url='https://t.me/share/url?url='+encodeURIComponent(link)+'&text='+encodeURIComponent(REFERRAL_SHARE_TEXT);
  try{if(tg&&tg.openTelegramLink)tg.openTelegramLink(url);else window.open(url,'_blank');}catch(_){try{window.open(url,'_blank');}catch(__){}}
}

// ── Onboarding: persona bo'yicha tavsiya etilgan odatlar ─────────────────
const OB_HABITS={
  student:[['📚','Kuniga 1 soat o\'qish'],['🌅','Erta turish'],['💧','Suv ichish'],['🧘','10 daqiqa meditatsiya']],
  pro:[['🌅','Erta turish'],['✍️','Kunlik reja tuzish'],['🏃','Sport / mashq'],['📵','Telefon detoks']],
  self:[['🏃','Sport / mashq'],['📚','Kitob o\'qish'],['🧘','Meditatsiya'],['💧','Suv ichish']],
  mixed:[['🌅','Erta turish'],['🏃','Sport / mashq'],['📚','Kitob o\'qish'],['💧','Suv ichish']],
};
function renderObHabits(){
  const persona=localStorage.getItem('iz_persona')||'mixed';
  const list=OB_HABITS[persona]||OB_HABITS.mixed;
  State.obHabits=list.map((x,i)=>({icon:x[0],title:x[1],sel:i<2}));
  const el=document.getElementById('obHabitOpts');if(!el)return;
  el.innerHTML=State.obHabits.map((h,i)=>`<div class="opt ${h.sel?'sel':''}" data-i="${i}"><span class="em">${h.icon}</span><div><div>${esc(h.title)}</div></div></div>`).join('');
  el.querySelectorAll('.opt').forEach(o=>o.onclick=()=>{const i=+o.dataset.i;State.obHabits[i].sel=!State.obHabits[i].sel;o.classList.toggle('sel');});
}

// Odat qo'shish modalida chiqadigan belgilar (emoji picker) — foydalanuvchi
// so'ragan aynan ro'yxat. Default belgi endi 🏃 (birinchi element).
const HABIT_ICONS=['🏃','💪','🌅','🛏️','💧','🍽️','🙏','📚','📖','💻','🧠','✍️','💼','🎯','💸','🧹','❤️','🚭','🫂','🛒','🚗'];
const WD_SHORT=['Du','Se','Cho','Pa','Ju','Sha','Ya'];

function habitMetaLabel(h){
  // Takrorlanish
  let rep;
  if((h.frequency||'daily')==='weekly'&&Array.isArray(h.weekdays)&&h.weekdays.length&&h.weekdays.length<7){
    rep=h.weekdays.map(i=>WD_SHORT[i]).join(', ');
  }else{rep='Har kuni';}
  // Davomiylik
  let dur='Doimiy';
  if((h.duration_type||'permanent')==='days'&&h.target_days){
    if(h.finished)dur='Tugadi';
    else if(h.days_left!=null)dur=h.days_left+' kun qoldi';
    else dur=h.target_days+' kun';
  }
  return {rep,dur};
}

async function loadHabitsAPI(){try{State.habits=await api('/api/webapp/habits');}catch(e){console.warn('habits',e);State.habits=[];}renderHabitsPage();}

function renderHabitsPage(){
  const today=document.getElementById('habitToday');const trk=document.getElementById('habitTracker');
  const isTracker=State.habitView==='tracker';
  if(today)today.classList.toggle('hidden',isTracker);
  if(trk)trk.classList.toggle('hidden',!isTracker);
  document.querySelectorAll('#habitViewSeg .hvs').forEach(s=>s.classList.toggle('active',s.dataset.hv===State.habitView));
  if(isTracker){renderTracker();}else{renderHabits();renderHabitSummary();}
}

// Odat shu kuni rejadami (frontend — backend bilan bir xil mantiq)
function habitDueOn(h,d){
  const ds=ymd(d);
  if(h.start_date&&ds<h.start_date)return false;
  if(h.end_date&&ds>h.end_date)return false;
  if((h.frequency||'daily')==='weekly'){const wd=(d.getDay()+6)%7;return Array.isArray(h.weekdays)&&(h.weekdays.length===0||h.weekdays.includes(wd));}
  return true;
}

function renderTracker(){
  const wrap=document.getElementById('trackerWrap');if(!wrap)return;
  if(!State.trackerWeekStart)State.trackerWeekStart=startOfWeek(new Date());
  const s=State.trackerWeekStart;const e=addDays(s,6);
  setText('trkRange',formatRange(s,e));
  if(!State.habits.length){wrap.innerHTML=emptyState('✅','Hozircha odat yo\'q','Odat qo\'shsangiz, bu yerda tracker chiqadi');return;}
  const todayStr=ymd(new Date());
  const days=[];for(let i=0;i<7;i++)days.push(addDays(s,i));
  let head='<th class="tcorner">Odat</th>';
  days.forEach(d=>{const it=ymd(d)===todayStr;head+=`<th class="${it?'ttoday':''}"><span class="twd">${UZ_DOW_SHORT[(d.getDay()+6)%7]}</span><span class="tdd">${d.getDate()}</span></th>`;});
  let rows='';
  State.habits.forEach(h=>{
    const logset=new Set(h.log_dates||[]);
    let cells='';
    days.forEach(d=>{
      const ds=ymd(d);const done=logset.has(ds);const future=ds>todayStr;const due=habitDueOn(h,d);
      let cls='tcell';if(done)cls+=' done';else if(future)cls+=' future';else if(!due)cls+=' nodue';
      const inner=done?'✓':(due&&!future?esc(h.icon||''):'');
      const tappable=due&&!future;
      cells+=`<td><div class="${cls}" ${tappable?`data-hid="${h.id}" data-d="${ds}"`:''}>${inner}</div></td>`;
    });
    rows+=`<tr><td class="tname">${esc(h.icon||'✅')} ${esc(h.title)}</td>${cells}</tr>`;
  });
  wrap.innerHTML=`<table><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table>`;
  wrap.querySelectorAll('.tcell[data-hid]').forEach(c=>c.onclick=async()=>{
    const id=+c.dataset.hid;const ds=c.dataset.d;const h=State.habits.find(x=>x.id===id);if(!h)return;
    const logset=new Set(h.log_dates||[]);const next=!logset.has(ds);
    try{const snap=await apiHabitToggle(id,next,ds);Object.assign(h,snap);renderTracker();if(next){try{tg?.HapticFeedback?.impactOccurred?.('light');}catch(_){}}}catch(_){toast('Xato!',true);}
  });
}

function renderHabitSummary(){const el=document.getElementById('habitSummary');if(!el)return;const tot=State.habits.length;const dueToday=State.habits.filter(h=>h.due_today&&!h.finished);const doneToday=dueToday.filter(h=>h.done_today).length;const best=State.habits.reduce((m,h)=>Math.max(m,h.streak||0),0);if(!tot){el.innerHTML='';return;}el.innerHTML=`<div class="hs-card"><div class="v">${doneToday}/${dueToday.length}</div><div class="l">Bugun bajarildi</div></div><div class="hs-card"><div class="v">${best}</div><div class="l">Eng uzun streak</div></div><div class="hs-card"><div class="v">${tot}</div><div class="l">Jami odat</div></div>`;}

// Odatlar ro'yxati — vaqti bo'yicha saralanadi (erta eslatma tepada,
// vaqtsizlar oxirda). Qo'shilgan tartibi bo'yicha emas.
function _habitSortKey(h){return (h.reminder_time && /^\d\d:\d\d/.test(h.reminder_time))?h.reminder_time:'99:99';}
function _sortHabitsByTime(arr){return arr.slice().sort((a,b)=>_habitSortKey(a).localeCompare(_habitSortKey(b)));}
function renderHabits(){
  const w=document.getElementById('habitsList');if(!w)return;
  if(!State.habits.length){w.innerHTML=emptyState('✅','Hozircha odat yo\'q','Har kuni takrorlanadigan odat qo\'shing — streak yig\'ing');return;}
  const sorted=_sortHabitsByTime(State.habits);
  w.innerHTML=sorted.map((h,i)=>{
    const m=habitMetaLabel(h);
    const notDue=!h.due_today||h.finished;
    const checkInner=h.finished?'🏁':(h.done_today?'✓':esc(h.icon||'✅'));
    // Meta chapdan: eslatma vaqti (bo'lsa), streak, takrorlanish, davomiylik.
    const timeBadge=h.reminder_time?`<span class="hbadge">⏰ ${esc(h.reminder_time)}</span>`:'';
    return `<div class="habit ${h.done_today?'done':''} ${h.finished?'finished':''}" data-id="${h.id}" style="animation-delay:${i*55}ms"><div class="hcheck" data-act="toggle" title="${notDue?'Bugun rejada yo\'q':'Bugun bajarildi'}">${checkInner}</div><div class="hbody"><div class="ttl">${esc(h.title)}</div><div class="meta">${timeBadge}<span class="hstreak">🔥 ${h.streak||0} kun</span><span class="hbadge">🔁 ${esc(m.rep)}</span><span class="hbadge">⏳ ${esc(m.dur)}</span></div></div><div class="hactions"><button class="edit" data-act="edit" aria-label="Tahrirlash"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M12 20h9M16.5 3.5a2.121 2.121 0 1 1 3 3L7 19l-4 1 1-4z"/></svg></button><button class="del" data-act="del" aria-label="O'chirish"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M3 6h18M19 6l-2 14H7L5 6m5 4v6m4-6v6M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/></svg></button></div></div>`;
  }).join('');
  bindHabitActions();
}

function bindHabitActions(){document.querySelectorAll('#habitsList .habit').forEach(row=>{const id=+row.dataset.id;
  row.querySelector('[data-act="toggle"]').onclick=async e=>{e.stopPropagation();const h=State.habits.find(x=>x.id===id);if(!h)return;if(h.finished){toast('🏁 Bu odat muddati tugagan',true);return;}if(!h.due_today){toast('📅 Bu odat bugun rejada yo\'q',true);return;}const next=!h.done_today;try{const snap=await apiHabitToggle(id,next);Object.assign(h,snap);renderHabits();renderHabitSummary();if(next){confetti(28);try{tg?.HapticFeedback?.notificationOccurred?.('success');}catch(_){}toast('🔥 '+(snap.streak||0)+' kun streak!');}else{toast('Belgilash olindi');}}catch(err){toast('Xato!',true);}};
  row.querySelector('[data-act="edit"]').onclick=e=>{e.stopPropagation();const h=State.habits.find(x=>x.id===id);if(h)openHabitModal(h);};
  row.querySelector('[data-act="del"]').onclick=async e=>{e.stopPropagation();if(!await confirmDialog({title:'Odatni o\'chirish',message:'Bu odat va uning tarixi o\'chiriladi. Davom etasizmi?'}))return;try{await apiHabitDelete(id);State.habits=State.habits.filter(x=>x.id!==id);renderHabits();renderHabitSummary();toast('🗑 O\'chirildi');}catch(_){toast('Xato!',true);}};});}

function renderHabitIconPick(){const el=document.getElementById('habitIconPick');if(!el)return;el.innerHTML=HABIT_ICONS.map(em=>`<div class="em ${em===State.habitIcon?'sel':''}" data-em="${em}">${em}</div>`).join('');el.querySelectorAll('.em').forEach(b=>b.onclick=()=>{State.habitIcon=b.dataset.em;el.querySelectorAll('.em').forEach(x=>x.classList.toggle('sel',x.dataset.em===State.habitIcon));});}

function renderHabitWeekdays(){const el=document.getElementById('hWeekdays');if(!el)return;el.innerHTML=WD_SHORT.map((n,i)=>`<div class="wdc ${State.habitWeekdays.includes(i)?'sel':''}" data-wd="${i}">${n}</div>`).join('');el.querySelectorAll('.wdc').forEach(c=>c.onclick=()=>{const i=+c.dataset.wd;if(State.habitWeekdays.includes(i))State.habitWeekdays=State.habitWeekdays.filter(x=>x!==i);else State.habitWeekdays.push(i);c.classList.toggle('sel');});}

function applyHabitFreqUI(){document.querySelectorAll('#hFreqSeg .hseg-item').forEach(it=>it.classList.toggle('active',it.dataset.f===State.habitFreq));const wd=document.getElementById('hWeekdays');if(wd)wd.style.display=State.habitFreq==='weekly'?'flex':'none';}
function applyHabitDurUI(){document.querySelectorAll('#hDurSeg .hseg-item').forEach(it=>it.classList.toggle('active',it.dataset.d===State.habitDur));const dw=document.getElementById('hDaysWrap');if(dw)dw.style.display=State.habitDur==='days'?'block':'none';}
function applyHabitRemUI(){document.querySelectorAll('#hRemSeg .hseg-item').forEach(it=>it.classList.toggle('active',it.dataset.r===State.habitRem));const rw=document.getElementById('hRemWrap');if(rw)rw.style.display=State.habitRem==='on'?'block':'none';}

function openHabitModal(habit){State.habitModal={id:habit?habit.id:null};State.habitIcon=(habit&&habit.icon)||'🏃';State.habitFreq=(habit&&habit.frequency)||'daily';State.habitDur=(habit&&habit.duration_type)||'permanent';State.habitWeekdays=(habit&&Array.isArray(habit.weekdays))?habit.weekdays.slice():[];State.habitRem=(habit&&habit.reminder_time)?'on':'off';setText('habitModalTitle',habit?'Odatni tahrirlash':'Yangi odat');const t=document.getElementById('hTitle');if(t)t.value=habit?habit.title:'';const d=document.getElementById('hDesc');if(d)d.value=habit&&habit.description?habit.description:'';const td=document.getElementById('hTargetDays');if(td)td.value=(habit&&habit.target_days)?habit.target_days:'';
  fillTimeSelectsFor('hRemHour','hRemMin');
  let rh='20',rm='00';
  if(habit&&habit.reminder_time&&habit.reminder_time.includes(':')){const pp=habit.reminder_time.split(':');rh=pad(parseInt(pp[0],10)||0);rm=pad(Math.round((parseInt(pp[1],10)||0)/5)*5%60);}
  const rhSel=document.getElementById('hRemHour');if(rhSel)rhSel.value=rh;
  const rmSel=document.getElementById('hRemMin');if(rmSel)rmSel.value=rm;
  renderHabitIconPick();renderHabitWeekdays();applyHabitFreqUI();applyHabitDurUI();applyHabitRemUI();const back=document.getElementById('habitModalBack');if(back)back.classList.add('show');setTimeout(()=>{const f=document.getElementById('hTitle');if(f)f.focus();},300);}
function closeHabitModal(){
  const b=document.getElementById('habitModalBack');if(b)b.classList.remove('show');
  State.forMemberContext=null;
}
async function saveHabitModal(){const t=(document.getElementById('hTitle')?.value||'').trim();if(!t){toast('Sarlavha bo\'sh',true);return;}const desc=(document.getElementById('hDesc')?.value||'').trim();
  const freq=State.habitFreq||'daily';
  let weekdays=null;
  if(freq==='weekly'){weekdays=(State.habitWeekdays||[]).slice().sort((a,b)=>a-b);if(!weekdays.length){toast('⏰ Kamida bitta kun tanlang',true);return;}}
  const dur=State.habitDur||'permanent';
  let targetDays=null;
  if(dur==='days'){targetDays=parseInt(document.getElementById('hTargetDays')?.value||'0',10);if(!targetDays||targetDays<1){toast('⏰ Necha kun davom etishini kiriting',true);return;}}
  const remOn=State.habitRem==='on';
  let reminderTime=null;
  if(remOn){const rh=document.getElementById('hRemHour')?.value||'20';const rm=document.getElementById('hRemMin')?.value||'00';reminderTime=rh+':'+rm;}
  const body={title:t,description:desc||null,icon:State.habitIcon||'🏃',frequency:freq,weekdays:weekdays,duration_type:dur,target_days:targetDays,reminder_time:reminderTime,clear_reminder:!remOn};
  const isEdit=!!State.habitModal.id;
  // ── Boshqa a'zo uchun yaratish ──
  if(!isEdit && State.forMemberContext){
    const ctx=State.forMemberContext;
    try{await apiForMemberHabit(ctx.groupId, ctx.userId, body);}
    catch(e){
      const m=String(e&&e.message||'');
      if(m.includes('402')){toast('⚠️ A\'zoning bepul odat limiti tugagan',true);return;}
      if(m.includes('403')){toast('🛡 A\'zo sizga ruxsat bermagan',true);return;}
      toast('Xato: '+m,true);return;
    }
    State.forMemberContext=null;
    closeHabitModal();
    toast('✨ '+ctx.name+' uchun odat qo\'shildi');
    try{await openMember(ctx.userId);}catch(_){}
    return;
  }
  try{if(isEdit){const nh=await apiHabitUpdate(State.habitModal.id,body);const idx=State.habits.findIndex(x=>x.id===State.habitModal.id);if(idx>=0)State.habits[idx]={...State.habits[idx],...nh};toast('✓ Yangilandi');}else{const nh=await apiHabitCreate(body);State.habits.push(nh);toast('✨ Odat qo\'shildi');}closeHabitModal();renderHabitsPage();}catch(e){const m=String(e&&e.message||'');if(m.includes('402')){closeHabitModal();return;/* Premium dialog global api() da avtomatik ochiladi */}toast('Xato: '+m,true);}}

// ── Ism tahrirlash ──────────────────────────────────────────────────────
function openNameModal(){const inp=document.getElementById('nName');if(inp)inp.value=State.displayName||State.user?.first_name||'';const back=document.getElementById('nameModalBack');if(back)back.classList.add('show');setTimeout(()=>{if(inp){inp.focus();inp.select();}},300);}
function closeNameModal(){const b=document.getElementById('nameModalBack');if(b)b.classList.remove('show');}
async function saveNameModal(){const nm=(document.getElementById('nName')?.value||'').trim();if(!nm){toast('Ism bo\'sh',true);return;}try{const res=await apiProfileUpdate(nm);applyUserName(res.full_name||nm);closeNameModal();toast('✓ Ism saqlandi');}catch(e){toast('Xato: '+String(e&&e.message||''),true);}}

// Sarlavhadagi bosh emoji-ni olib tashlaydi (rankEmoji alohida ko'rsatilgani uchun
// "🌱 🌱 Boshlovchi" kabi takror chiqmasligi uchun)
function stripLeadEmoji(s){try{return String(s||'').replace(/^[\s\p{Extended_Pictographic}\uFE0F\u200D]+/u,'').trim();}catch(_){return String(s||'').trim();}}
// Raqamlarni silliq "sanab" ko'rsatadi (count-up animatsiya)
function countUp(id,to,suffix){const el=document.getElementById(id);if(!el)return;to=Math.round(Number(to)||0);suffix=suffix||'';const from=parseInt(String(el.textContent).replace(/[^\d-]/g,''),10)||0;if(from===to){el.textContent=to+suffix;return;}const dur=750,t0=performance.now();const step=now=>{const p=Math.min(1,(now-t0)/dur);const v=Math.round(from+(to-from)*(1-Math.pow(1-p,3)));el.textContent=v+suffix;if(p<1)requestAnimationFrame(step);};requestAnimationFrame(step);}

function renderHero(){
  const snap=State.snap||{};
  const lvl=snap.level||1;
  const xpInLvl=snap.xp_in_level||0;
  const xpNeed=snap.xp_needed||100;
  const pct=snap.xp_percent||0;
  const ds=snap.discipline_score!=null?snap.discipline_score:50;
  const streak=snap.streak||State.user?.streak||0;
  const tDone=snap.today_done||0;
  const tTot=snap.today_total||0;
  setText('rankEmoji',snap.rank_emoji||'🌱');
  setText('rankTitle',stripLeadEmoji(snap.rank_title)||'Boshlovchi');
  setText('levelNum',lvl);
  setText('xpInLvl',xpInLvl);
  setText('xpNeeded',xpNeed);
  setText('xpPctLabel',pct+'%');
  countUp('streakCount',streak);
  setText('todayStat',tDone+'/'+tTot);
  const riskChip=document.getElementById('streakRiskChip');
  if(riskChip){if(snap.streak_at_risk&&streak>=2){riskChip.classList.add('warn');riskChip.innerHTML='<span class="em">⚠️</span> Streak xavf ostida';}else{riskChip.classList.remove('warn');riskChip.innerHTML='<span class="em">📋</span> '+tDone+'/'+tTot+' bugun';}}
  setTimeout(()=>{const xb=document.getElementById('xpBar');if(xb)xb.style.width=pct+'%';const C=2*Math.PI*42;const ring=document.getElementById('dsRing');if(ring)ring.setAttribute('stroke-dashoffset',String(C*(1-ds/100)));countUp('dsValue',ds);countUp('totalXpLabel',(snap.xp||0),' XP');const dv=document.getElementById('dsValue');if(dv){dv.classList.remove('pop');void dv.offsetWidth;dv.classList.add('pop');}},120);
}

async function loadSnapshot(){try{const s=await api('/api/webapp/stats');State.snap=s;const totalScore=(s.total_score!=null?s.total_score:s.xp)||0;State.user=Object.assign({},State.user||{},{streak:s.streak,total_score:totalScore});const _rawShown=localStorage.getItem('iz_shown_achs');const _firstRun=(_rawShown===null);let shownAchs;try{shownAchs=new Set(JSON.parse(_rawShown||'[]'));}catch(_){shownAchs=new Set();}const newAchs=[];(s.achievements||[]).forEach(a=>{if(!shownAchs.has(a.code)){if(!_firstRun)newAchs.push(a);shownAchs.add(a.code);}});try{localStorage.setItem('iz_shown_achs',JSON.stringify([...shownAchs]));}catch(_){}State.knownAchs=shownAchs;renderHero();if(newAchs.length){newAchs.forEach((a,i)=>setTimeout(()=>showUnlock(a),i*900));}maybePeakUpsell(s);setText('pfStreak',s.streak||0);setText('stStreak',s.streak||0);setText('msScore',totalScore);setText('pfScore',totalScore);setText('stTotal',totalScore);}catch(e){console.warn('snapshot',e);}}

async function loadQuest(){try{const q=await api('/api/webapp/quest');const c=document.getElementById('questCard');if(!c)return;c.style.display='flex';c.classList.toggle('done',!!q.completed);setText('qIcon',q.icon||'🎯');setText('qTitle',q.title||'');setText('qSub',q.subtitle||'');const pct=q.target?Math.round((q.progress||0)*100/q.target):0;setTimeout(()=>{const qp=document.getElementById('qProg');if(qp)qp.style.width=pct+'%';},150);setText('qMetaProg',(q.progress||0)+'/'+(q.target||0));setText('qReward',q.reward_xp?('+'+q.reward_xp+' XP'):'✓');}catch(e){console.warn('quest',e);}}

async function loadCoach(){try{const m=await api('/api/webapp/coach');setText('coachIco',m.icon||'✨');setText('coachMsg',m.text||'');setText('coachTag',(m.tone||'coach').toUpperCase());}catch(e){console.warn('coach',e);}}

// Belgilash (toggle) tez-tez bosilganda /stats va /quest ni HAR bosishda emas,
// coalesce qilib (bir necha bosishni bitta so'rovga birlashtirib) yangilaymiz.
// UI baribir darhol (local state + xpPop) yangilanadi.
let _statsRefreshTimer=null;
function scheduleStatsRefresh(withQuest){
  if(_statsRefreshTimer)clearTimeout(_statsRefreshTimer);
  const wantQuest=withQuest!==false;
  _statsRefreshTimer=setTimeout(()=>{
    _statsRefreshTimer=null;
    loadSnapshot();
    if(wantQuest)loadQuest();
  },550);
}

// ── AI Chat (ephemeral — saqlanmaydi) ───────────────────────────────────
function chatAppend(role,text){const log=document.getElementById('chatLog');if(!log)return null;const el=document.createElement('div');el.className='chat-msg '+(role==='user'?'user':role==='err'?'err':'bot');el.textContent=text;log.appendChild(el);log.scrollTop=log.scrollHeight;return el;}
function chatTyping(on){const log=document.getElementById('chatLog');if(!log)return;let t=document.getElementById('chatTyping');if(on){if(!t){t=document.createElement('div');t.id='chatTyping';t.className='chat-typing';t.innerHTML='<i></i><i></i><i></i>';log.appendChild(t);}log.scrollTop=log.scrollHeight;}else if(t){t.remove();}}
function chatSetLimit(s){const el=document.getElementById('chatLimit');if(!el)return;if(s&&s.is_premium){el.style.display='inline-block';el.textContent='💎 Cheksiz';}else if(s&&typeof s.remaining==='number'&&s.limit>0){el.style.display='inline-block';el.textContent='💬 '+s.remaining+'/'+s.limit;}else{el.style.display='none';}}
function chatGreet(){if(State.chatGreeted)return;State.chatGreeted=true;const nm=State.user?.first_name||'do\'st';chatAppend('bot','Salom, '+nm+'! 🌱 Men Intizom AI — sening shaxsiy murabbiyingman. Maqsad va rejalaringni ko\'rib turibman. Savolingni yoz — men sening rejalaring va kayfiyatingga qarab javob beraman.');}

async function chatSend(text){
  text=(text||'').trim();if(!text||State.chatBusy)return;
  const input=document.getElementById('chatInput');const sendBtn=document.getElementById('chatSend');const sugg=document.getElementById('chatSugg');
  if(sugg)sugg.style.display='none';
  chatAppend('user',text);
  State.chatHistory=State.chatHistory||[];State.chatHistory.push({role:'user',content:text});
  if(input){input.value='';input.style.height='auto';}
  State.chatBusy=true;if(sendBtn)sendBtn.disabled=true;chatTyping(true);
  try{
    const data=await api('/api/webapp/ai/chat',{method:'POST',body:JSON.stringify({messages:State.chatHistory})});
    chatTyping(false);
    const reply=data.reply||'…';
    chatAppend('bot',reply);
    State.chatHistory.push({role:'assistant',content:reply});
    chatSetLimit(data);
    try{tg?.HapticFeedback?.impactOccurred('light');}catch(_){}
  }catch(e){
    chatTyping(false);
    const msg=String(e&&e.message||'');
    if(msg.includes('402')){
      // Premium dialog global api() da avtomatik ochilgan — bu yerda faqat
      // chat log'ga qisqa xabar qoldiramiz.
      chatAppend('err','💎 AI Coach faqatgina Premium foydalanuvchilar uchun.');
    }else if(msg.includes('404')){
      chatAppend('err','Avval botda /start bosing — keyin AI bilan suhbatlashasiz.');
    }else{
      chatAppend('err','⚠️ Bog\'lanishda nosozlik. Yana urinib ko\'r.');
    }
  }finally{
    State.chatBusy=false;if(sendBtn)sendBtn.disabled=false;
    if(input)input.focus();
  }
}

async function loadCheckin(){try{const c=await api('/api/webapp/checkin');if(!c)return;if(c.mood){document.querySelectorAll('#moodRow .mood-pill').forEach(p=>p.classList.toggle('active',p.dataset.mood===c.mood));State.checkinMood=c.mood;}if(c.energy){document.querySelectorAll('#energyRow .energy-cell').forEach(p=>p.classList.toggle('active',+p.dataset.en===c.energy));State.checkinEnergy=c.energy;}}catch(e){console.warn('checkin',e);}}

async function saveCheckin(payload){try{await api('/api/webapp/checkin',{method:'POST',body:JSON.stringify(payload)});}catch(_){toast('Saqlashda xato',true);}}

// ── Premium / paywall ───────────────────────────────────────────────────
function openPaywall(){
  const ov=document.getElementById('paywall');
  if(!ov)return;
  const isPremium=!!(State.sub&&State.sub.is_premium);
  const h=ov.querySelector('h1');
  const cta=document.getElementById('pwCta');
  // Sarlavha: "IntizomAi Premium 💎" — 💎 sarlavha yonida, subtitle yo'q.
  if(h)h.innerHTML='IntizomAi <span class="pw-pro">Premium</span> <span class="pw-title-gem" aria-hidden="true">💎</span>';
  if(cta)cta.textContent = isPremium ? '💳 Uzaytirish' : '💎 Tarifni tanlash';
  // Tariflar tugmalari — bosilganda to'g'ridan-to'g'ri checkoutga o'tadi.
  renderPaywallPlans(State.sub&&State.sub.plans);
  ov.classList.add('show');
  try{tg?.HapticFeedback?.notificationOccurred?.('warning');}catch(_){}
}
function closePaywall(){const ov=document.getElementById('paywall');if(ov)ov.classList.remove('show');}
// Peak-moment upsell: streak milestone'ida (3,7,14,30,50,100) bepul foydalanuvchiga
// bir marta (har milestone uchun) yumshoq premium taklifi ko'rsatamiz — eng kuchli
// emotsional onda (P1). Premium foydalanuvchiga ko'rsatilmaydi.
function maybePeakUpsell(snap){
  try{
    if(!snap)return;
    if(State.sub&&State.sub.is_premium)return;
    const streak=snap.streak||0;
    const milestones=[3,7,14,30,50,100];
    if(!milestones.includes(streak))return;
    const key='iz_peak_ms_'+streak;
    if(localStorage.getItem(key))return;
    localStorage.setItem(key,'1');
    setTimeout(()=>toast('🔥 '+streak+' kunlik streak — zo\'r ketyapsan!'),500);
    setTimeout(()=>{if(!(State.sub&&State.sub.is_premium))openPaywall();},1700);
  }catch(_){}
}
// Paywall'dagi tarif kartochkalari — YAGONA QATORDA (foydalanuvchi so'ragan
// yangi format):
//   ✅ 1 oylik    39 900 so'm
//   ⭐ 3 oy       79 900 so'm (33% tejaysiz)
//   💎 12 oy      179 900 so'm (≈ 14 990 so'm/oy)
//
// Har bir karta: chap tomonda [emoji] [title], o'ng tomonda [price] so'm [(tag)].
// `tag` qiymatlari SUBSCRIPTION_PLANS (bot/config.py) dan keladi va allaqachon
// ma'noli matn saqlaydi ("33% tejaysiz", "≈ 14 990 so'm/oy"). Admin panelidan
// tarif tagi o'zgartirilsa, foydalanuvchiga darhol ko'rinadi.
function renderPaywallPlans(plans){
  const el=document.getElementById('pwPlans');
  if(!el)return;
  if(!plans||!plans.length){el.innerHTML='';return;}

  el.innerHTML=plans.map(p=>{
    const tag=(p.tag||'').trim();
    const emoji=(p.emoji||'💎');
    // Featured — konfiguratsiyada tag bo'lsa (odatda 3 oy "33% tejaysiz")
    // gradient chetlik va ustuvor vizual og'irlik oladi.
    const isFeatured = tag !== '';
    return `<button class="pw-plan pw-plan-btn${isFeatured?' featured':''}" data-plan="${esc(p.key)}" type="button" aria-label="${esc(p.title)} tarifi">
      <span class="pw-plan-title"><span class="pw-plan-emoji">${emoji}</span>${esc(p.title)}</span>
      <span class="pw-plan-price-line">
        <span class="pw-plan-amount">${esc(p.price_label)} so'm</span>${tag?`<span class="pw-plan-tag">(${esc(tag)})</span>`:''}
      </span>
    </button>`;
  }).join('');

  el.querySelectorAll('.pw-plan-btn').forEach(btn=>{
    btn.onclick=()=>startCheckout(btn.dataset.plan,btn);
  });
}

// Mini App ichidan tarif tanlansa — foydalanuvchini BOTGA qaytaradi.
// To'lov jarayoni endi faqat bot ichida amalga oshiriladi (yagona oqim,
// xavfsizlik va debug qulayligi uchun). Backend `bot_url` (t.me deep-link)
// qaytaradi va shuni Telegram ichida ochamiz — Mini App yopiladi, bot chati
// ochilib, tanlangan tarifning to'lov usulini tanlash oynasi ko'rsatiladi.
async function startCheckout(planKey,btn){
  if(!planKey)return;
  try{tg?.HapticFeedback?.impactOccurred?.('medium');}catch(_){}
  const orig=btn?btn.innerHTML:null;
  if(btn){btn.disabled=true;btn.classList.add('loading');btn.innerHTML='<span class="pn">⏳ Botga o\'tkazilmoqda…</span>';}
  try{
    const res=await api('/api/webapp/checkout',{method:'POST',body:JSON.stringify({plan:planKey})});
    // Yangi backend: `bot_url` — Telegram deep-link. Eski nomi `checkout_url`
    // ham qaytariladi (backward-compat).
    const url=(res&&(res.bot_url||res.checkout_url))||'';
    if(!url){throw new Error('Bot havolasi olinmadi');}
    // t.me deep-link uchun `openTelegramLink` ishlatiladi — bu Mini App'ni
    // yopib, botga o'tishni RASMIY yo'l. `openLink` esa Telegram browser'ini
    // ochib, mini appda qoladigan qilib qo'yardi (bu esa toʻgʻri kelmaydi).
    const isTme=/^https?:\/\/t\.me\//i.test(url);
    try{
      if(isTme&&tg&&typeof tg.openTelegramLink==='function'){tg.openTelegramLink(url);}
      else if(tg&&tg.openLink){tg.openLink(url,{try_instant_view:false});}
      else{window.open(url,'_blank');}
    }catch(_){
      try{window.open(url,'_blank');}catch(__){}
    }
    toast('Botga o\'tkazildik. To\'lovni bot ichida yakunlang 💳',false);
    // Mini App'ni yopamiz — foydalanuvchi endi bot chatida.
    try{setTimeout(()=>{try{tg?.close?.();}catch(_){}},400);}catch(_){}
  }catch(e){
    const m=String(e&&e.message||e);
    if(m.includes('404')){
      toast('Avval botda /start bosing.',true);
    }else if(m.includes('400')){
      toast('Noma\'lum tarif.',true);
    }else{
      toast('Botga o\'tishda muammo bo\'ldi. Botni qo\'lda oching va «💎 Premium» tugmasini bosing.',true);
    }
  }finally{
    if(btn){btn.disabled=false;btn.classList.remove('loading');if(orig)btn.innerHTML=orig;}
  }
}

// Mini App'dan botga umumiy Premium menyusiga o'tish (aniq tarif tanlanmagan
// holda). Bot deep-link `/start premium` ni ochadi — bot Premium sahifasini
// (tariflar ro'yxatini) ko'rsatadi. Foydalanuvchi tarifni BOT ichida tanlaydi.
// Bu paywall'ning katta CTA tugmasi uchun (pwCta) ishlatiladi.
function startCheckoutGeneric(){
  // Bot username config'dan olinishi mumkin, ammo bizda hozircha frontend'da
  // sozlamaydi. `/api/webapp/checkout` uchun plan majburiy. Shu sabab
  // biz to'g'ridan-to'g'ri t.me deep-link'ni yasab ochamiz —
  // premium_service.py BOT_USERNAME'i muhitdan keladi. Frontend uchun
  // `State.sub.bot_username` maydonini backend'dan olamiz (agar yo'q bo'lsa,
  // fallback: env yoki "intizomAi_bot").
  const uname=(State.sub&&State.sub.bot_username)||'intizomAi_bot';
  const url='https://t.me/'+String(uname).replace(/^@/,'')+'?start=premium';
  try{
    const isTme=/^https?:\/\/t\.me\//i.test(url);
    if(isTme&&tg&&typeof tg.openTelegramLink==='function'){
      tg.openTelegramLink(url);
    }else if(tg&&tg.openLink){
      tg.openLink(url,{try_instant_view:false});
    }else{
      window.open(url,'_blank');
    }
    toast('Botga o\'tkazildik. Tarifni bot ichida tanlang 💎',false);
    // Mini App'ni yopamiz — foydalanuvchi endi bot chatida.
    setTimeout(()=>{try{tg?.close?.();}catch(_){}},400);
  }catch(_){
    try{window.open(url,'_blank');}catch(__){}
  }
}

function applyPremiumUI(s){
  const box=document.getElementById('subStatus');
  const icon=document.getElementById('ssIcon');
  const title=document.getElementById('ssTitle');
  const sub=document.getElementById('ssSub');
  const cta=document.getElementById('ssCta');
  const bar=document.getElementById('ssBar');
  if(!box)return;
  if(s&&s.is_premium){
    box.classList.add('premium');
    if(icon)icon.textContent='👑';
    if(title)title.textContent='Premium faol';
    let until='';
    if(s.premium_until){try{const d=new Date(s.premium_until);until=d.getDate()+' '+UZ_MONTHS_SHORT[d.getMonth()]+' '+d.getFullYear();}catch(_){}}
    const dl=s.days_left||0;
    if(sub)sub.textContent=(s.plan_title?s.plan_title:'Obuna')+' · '+dl+' kun qoldi'+(until?' · '+until+' gacha':'');
    // Premium foydalanuvchi ham obunani UZAYTIRISH imkoniyatiga ega bo'lsin
    // (kunlar joriy tugash sanasi ustiga qo'shiladi).
    if(cta){cta.style.display='';cta.textContent='💳 Uzaytirish';}
    // progress: qolgan kun / tarif umumiy kuni
    if(bar){
      // Tarif nomi admin tomonidan o'zgartirilishi mumkin — shuning uchun
      // avval `s.plans` ichidan mos "days" ni qidiramiz (title bilan), aks
      // holda eski/yangi nomlar bilan fallback qilamiz.
      let totalDays=30;
      try{
        const found=((s.plans||[]).find(p=>p.title===s.plan_title||p.key===s.plan));
        if(found&&found.days)totalDays=found.days;
        else totalDays={'1 oy':30,'3 oy':90,'12 oy':365,'Oylik':30,'6 oy':180,'Yillik':365,'Sinov 7 kun':7}[s.plan_title]||30;
      }catch(_){}
      const pct=Math.max(4,Math.min(100,Math.round(dl*100/totalDays)));
      setTimeout(()=>{bar.style.width=pct+'%';},150);
    }
  }else{
    box.classList.remove('premium');
    if(icon)icon.textContent='🆓';
    if(title)title.textContent='Bepul rejim';
    if(sub)sub.textContent='Premium bilan barcha imkoniyatlar ochiladi.';
    if(cta){cta.style.display='';cta.textContent='💎 Premium olish';}
    if(bar)bar.style.width='0%';
  }
}
// Onboarding'ni faqat premium foydalanuvchiga, bir marta ko'rsatamiz
// Kalit yangilandi (v2): yaxshilangan tanishtiruv eski foydalanuvchilarga bir marta qayta ko'rsatiladi, keyin saqlanadi (qayta chiqmaydi)
function maybeShowOnboarding(){
  try{if(localStorage.getItem('iz_onboarded_v2'))return;}catch(_){}
  const ob=document.getElementById('onboarding');
  if(ob){
    // Umri davomida faqat BIR MARTA — ko'rsatish bilanoq belgilab qo'yamiz
    try{localStorage.setItem('iz_onboarded_v2','1');}catch(_){}
    setTimeout(()=>ob.classList.add('show'),350);
  }
}
async function loadSubscription(){
  try{
    const s=await api('/api/webapp/subscription');
    State.sub=s;
    try{localStorage.setItem('iz_premium',s.is_premium?'1':'0');}catch(_){}
    renderPaywallPlans(s.plans);
    applyPremiumUI(s);
    // Tema tanlash Premium bilan bog'liq (qulf badge/opacity). renderThemes()
    // DOMContentLoaded'da chaqirilgan bo'lardi (State.sub yo'q edi u paytda),
    // shuning uchun premium user'lar dastlab qulflangan tema ko'rar edi.
    // Endi subscription javobi kelgach QAYTA chaqiramiz — qulflar to'g'ri
    // qo'llanadi (premium user: ochiq, bepul: qulf).
    try{renderThemes();}catch(_){}
    // Bepul foydalanuvchi ham Mini App'ni to'liq KO'RA oladi (read/limited).
    // Paywall faqat limit oshganda yoki premium funksiya bosilganda ochiladi.
    closePaywall();
    maybeShowOnboarding();
    return !!s.is_premium;
  }catch(e){
    console.warn('subscription',e);
    // Xato bo'lsa ham foydalanuvchini bloklamaymiz — bepul ko'rishda davom etadi.
    State.sub={is_premium:false};
    try{renderThemes();}catch(_){}
    closePaywall();
    return false;
  }
}

function renderInsights(){
  const PR=State.plansRange.length?State.plansRange:State.plans;
  const tod=new Date();
  const last7=PR.filter(p=>p.plan_date&&new Date(p.plan_date)>=addDays(tod,-7));
  const done7=last7.filter(p=>p.status==='done').length;
  const total7=last7.length;
  const rate=total7?Math.round(done7*100/total7):0;
  const streak=State.snap?.streak||0;
  const ds=State.snap?.discipline_score||50;
  const items=[];
  if(streak>=7)items.push({ic:'🔥',t:'Sen olov ustidasan',d:streak+' kunlik streak — top 5% foydalanuvchi.'});
  if(ds>=75)items.push({ic:'💎',t:'Discipline elite zonada',d:'Sen endi qiluvchi emas — qiluvchi shaxssan.'});
  if(rate>=80&&total7>=5)items.push({ic:'⚡',t:'Hafta zo\'r ketdi',d:done7+'/'+total7+' reja bajarildi (yuqori darajada).'});
  if(rate<40&&total7>=5)items.push({ic:'📈',t:'Bu hafta sustroq',d:'Bitta yengil reja qo\'shsang — momentum tiklanadi.'});
  if(ds<40)items.push({ic:'🎯',t:'Discipline tushyapti',d:'Bugun bitta kichik narsani bajar — score yana ko\'tarilad.'});
  if(streak===0&&PR.length>0)items.push({ic:'🌱',t:'Yangi boshlanish',d:'Birinchi qadam — eng qiyini. Ammo eng muhimi.'});
  if(!items.length)items.push({ic:'✨',t:'Hammasi joyida',d:'Davom et. Sen to\'g\'ri yo\'ldasan.'});
  document.getElementById('insights').innerHTML=items.map(i=>`<div class="insight"><div class="ic">${i.ic}</div><div class="body"><div class="t">${esc(i.t)}</div><div class="d">${esc(i.d)}</div></div></div>`).join('');
}

function showUnlock(a){const ov=document.getElementById('unlockOverlay');document.getElementById('unlockIcon').textContent=a.icon||'🏆';document.getElementById('unlockTitle').textContent=a.title||'';document.getElementById('unlockRarity').textContent=(a.rarity||'common').toUpperCase();ov.classList.add('show');confetti(50);try{tg?.HapticFeedback?.notificationOccurred('success');}catch(_){}}

function confetti(n){const colors=['#14b8a6','#06b6d4','#f59e0b','#ec4899','#a855f7','#22c55e','#f43f5e','#3b82f6'];for(let i=0;i<n;i++){const p=document.createElement('div');p.className='confetti-piece';p.style.background=colors[i%colors.length];p.style.left=(50+(Math.random()-.5)*40)+'%';p.style.top='-20px';p.style.setProperty('--cx',((Math.random()-.5)*400)+'px');p.style.animationDuration=(1.5+Math.random()*1.5)+'s';p.style.animationDelay=(Math.random()*0.3)+'s';document.body.appendChild(p);setTimeout(()=>p.remove(),3500);}}

function xpPop(amount){const el=document.createElement('div');el.className='xp-pop';el.textContent='+'+amount+' XP';document.body.appendChild(el);setTimeout(()=>el.remove(),1600);try{tg?.HapticFeedback?.impactOccurred('medium');}catch(_){}}


const HABIT_SCORE=5;
function planRowHTML(p,i){return `<div class="plan ${p.status==='done'?'done':''}" data-id="${p.id}" style="animation-delay:${i*60}ms"><div class="cbx ${p.status==='done'?'done':''}" data-act="toggle">${p.status==='done'?'✓':''}</div><div class="body"><div class="ttl">${esc(p.title)}</div><div class="meta">${p.scheduled_time||'Vaqt yo\'q'}${p.description?' • '+esc(p.description):''}</div></div><div class="score">+${p.score_value||0}</div><div class="actions"><button class="edit" data-act="edit" aria-label="Tahrirlash"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M12 20h9M16.5 3.5a2.121 2.121 0 1 1 3 3L7 19l-4 1 1-4z"/></svg></button><button class="del" data-act="del" aria-label="O'chirish"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M3 6h18M19 6l-2 14H7L5 6m5 4v6m4-6v6M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/></svg></button></div></div>`;}
function habitRowHTML(h,i){
  const done=h.done_today;
  // Eslatma vaqti bo'lsa ⏰ vaqt, bo'lmasa takrorlanish (🔁) ko'rsatiladi —
  // shunda vaqtsiz odatlar ham asosiy sahifada ma'noli ko'rinadi.
  const freqLabel=(h.frequency==='weekly')?'Haftalik':'Har kuni';
  const timePart=h.reminder_time?('⏰ '+esc(h.reminder_time)):('🔁 '+freqLabel);
  return `<div class="plan habit-row ${done?'done':''}" data-hid="${h.id}" style="animation-delay:${i*60}ms"><div class="cbx ${done?'done':''}" data-act="htoggle">${done?'✓':''}</div><div class="body"><div class="ttl">${esc(h.icon||'✅')} ${esc(h.title)}<span class="htag">Odat</span></div><div class="meta">${timePart}  ·  🔥 ${h.streak||0} kun</div></div><div class="score">+${HABIT_SCORE}</div></div>`;
}
function renderPlans(){
  const w=document.getElementById('plansList');if(!w)return;
  const isToday=ymd(State.selectedDate||new Date())===ymd(new Date());
  // Bugun uchun rejalar YONIDA odatlar ham ko'rsatiladi (faqat odatlar bo'limida
  // emas). Vaqtli/vaqtsiz — hammasi, agar bugun bajarilishi kerak bo'lsa.
  const habitItems=isToday?(State.habits||[]).filter(h=>h.due_today&&!h.finished):[];
  if(!State.plans.length&&!habitItems.length){w.innerHTML=emptyState('📋','Hozircha rejalar yo\'q','+ tugmasi orqali yangi reja yoki Odat bo\'limidan odat qo\'shing');return;}
  const items=[];
  State.plans.forEach(p=>items.push({t:p.scheduled_time||'99:99',kind:'plan',p}));
  habitItems.forEach(h=>items.push({t:h.reminder_time||'99:99',kind:'habit',h}));
  items.sort((a,b)=>String(a.t).localeCompare(String(b.t)));
  w.innerHTML=items.map((it,i)=>it.kind==='plan'?planRowHTML(it.p,i):habitRowHTML(it.h,i)).join('');
  bindPlanActions();bindHomeHabitActions();
}
function bindHomeHabitActions(){document.querySelectorAll('#plansList .plan[data-hid]').forEach(row=>{const id=+row.dataset.hid;const cb=row.querySelector('[data-act="htoggle"]');if(!cb)return;cb.onclick=async e=>{e.stopPropagation();const h=(State.habits||[]).find(x=>x.id===id);if(!h)return;const next=!h.done_today;try{const snap=await apiHabitToggle(id,next);Object.assign(h,snap);renderPlans();if(next){xpPop(HABIT_SCORE);confetti(30);try{tg?.HapticFeedback?.notificationOccurred?.('success');}catch(_){}toast('🔥 '+(snap.streak||0)+' kun streak!');}else{toast('Belgilash olindi');}scheduleStatsRefresh(false);}catch(_){toast('Xato!',true);}};});}
async function loadHomeHabits(){try{State.habits=await api('/api/webapp/habits');}catch(_){}renderPlans();}

// ── Statistika: Mening / Reyting ────────────────────────────────────────
function applyStatsView(){
  const mine=document.getElementById('statsMine');const rating=document.getElementById('statsRating');
  const isRating=State.statsView==='rating';
  if(mine)mine.classList.toggle('hidden',isRating);
  if(rating)rating.classList.toggle('hidden',!isRating);
  document.querySelectorAll('#statsSeg .hvs').forEach(s=>s.classList.toggle('active',s.dataset.sv===State.statsView));
  if(isRating)loadLeaderboard();
}
async function loadStatsHabits(){try{State.habits=await api('/api/webapp/habits');}catch(_){}renderHabitStats();try{renderTrend(30);}catch(_){}}
function habit30Rate(h){const logs=new Set(h.log_dates||[]);let due=0,done=0;const today=new Date();for(let i=0;i<30;i++){const d=addDays(today,-i);if(habitDueOn(h,d)){due++;if(logs.has(ymd(d)))done++;}}return due?Math.round(done*100/due):0;}
function renderHabitStats(){
  const grid=document.getElementById('habitStatGrid');const list=document.getElementById('habitStatList');
  const hs=State.habits||[];
  if(!hs.length){if(grid)grid.innerHTML='';if(list)list.innerHTML=emptyState('✅','Odat yo\'q','Odat bo\'limidan qo\'shing');return;}
  const dueToday=hs.filter(h=>h.due_today&&!h.finished);const doneToday=dueToday.filter(h=>h.done_today).length;
  const best=hs.reduce((m,h)=>Math.max(m,h.streak||0),0);
  const totalDone=hs.reduce((s,h)=>s+(h.total_done||0),0);
  if(grid)grid.innerHTML=`<div class="stat-card"><div class="ic-bg">✅</div><div class="l">Bugun</div><div class="v">${doneToday}/${dueToday.length}</div><div class="ch">bajarildi</div></div><div class="stat-card"><div class="ic-bg">🔥</div><div class="l">Eng uzun streak</div><div class="v">${best}</div><div class="ch">kun</div></div><div class="stat-card"><div class="ic-bg">📦</div><div class="l">Faol odatlar</div><div class="v">${hs.length}</div><div class="ch">ta</div></div><div class="stat-card"><div class="ic-bg">🎯</div><div class="l">Jami bajarilgan</div><div class="v">${totalDone}</div><div class="ch">marta</div></div>`;
  if(list)list.innerHTML=hs.map(h=>{const r=habit30Rate(h);return `<div class="lb-row"><div class="lb-av">${esc(h.icon||'✅')}</div><div class="lb-name">${esc(h.title)}<div style="font-size:11px;color:var(--text-2);font-weight:600">🔥 ${h.streak||0} kun · 30 kun: ${r}%</div></div><div class="lb-val">${r}%</div></div>`;}).join('');
}
const LB_UNIT={all:'ball',week:'ball',streak:'kun'};
function lbAvatar(r){if(r&&r.photo_url){const em=esc(r.emoji||'🌱');return `<div class="lb-av" data-em="${em}"><img src="${esc(r.photo_url)}" referrerpolicy="no-referrer" loading="lazy" onerror="this.parentNode.textContent=this.parentNode.dataset.em"></div>`;}return `<div class="lb-av">${esc((r&&r.emoji)||'🌱')}</div>`;}
async function loadLeaderboard(){
  const meEl=document.getElementById('lbMe');const listEl=document.getElementById('lbList');
  document.querySelectorAll('#lbSeg .hvs').forEach(s=>s.classList.toggle('active',s.dataset.lb===State.lbPeriod));
  if(listEl)listEl.innerHTML='<div class="empty-state"><p>Yuklanmoqda…</p></div>';
  if(meEl)meEl.innerHTML='';
  let d;try{d=await api('/api/webapp/leaderboard?period='+State.lbPeriod);}catch(e){if(listEl)listEl.innerHTML=emptyState('🏆','Reyting yuklanmadi','Keyinroq urinib ko\'ring');return;}
  const unit=LB_UNIT[State.lbPeriod]||'ball';
  const top=d.top||[];
  if(listEl)listEl.innerHTML=top.length?top.map(r=>{const medal=r.rank===1?'🥇':r.rank===2?'🥈':r.rank===3?'🥉':r.rank;const cls=r.rank<=3?(' lb-'+r.rank):'';return `<div class="lb-row${cls} ${r.is_me?'me':''}"><div class="lb-rank ${r.rank<=3?'top':''}">${medal}</div>${lbAvatar(r)}<div class="lb-name">${esc(r.name)}${r.is_me?' (siz)':''}</div><div class="lb-val">${r.value} ${unit}</div></div>`;}).join(''):emptyState('🏆','Hali reyting yo\'q','Birinchi bo\'ling!');
  if(meEl&&d.me&&!d.me.in_top){meEl.innerHTML=`<div style="text-align:center;font-size:11px;color:var(--text-3);margin:2px 0 8px">— sizning o'rningiz —</div><div class="lb-row me"><div class="lb-rank">${d.me.rank}</div>${lbAvatar(d.me)}<div class="lb-name">${esc(d.me.name)} (siz)</div><div class="lb-val">${d.me.value} ${unit}</div></div>`;}
}

function bindPlanActions(){document.querySelectorAll('#plansList .plan[data-id]').forEach(row=>{const id=+row.dataset.id;row.querySelector('[data-act="toggle"]').onclick=async e=>{e.stopPropagation();const p=State.plans.find(x=>x.id===id);if(!p)return;const _r=planBlockReason(p);if(_r==='past'){toast('⏰ O\'tib ketgan kun rejasini o\'zgartirib bo\'lmaydi',true);return;}if(p.status!=='done'&&_r==='future'){toast('⏰ Bu rejaning vaqti hali kelmagan',true);return;}const ns=p.status==='done'?'pending':'done';try{const wasNotDone=p.status!=='done';const np=await apiPlanUpdate(id,{status:ns});Object.assign(p,np);renderPlans();renderHero();if(ns==='done'&&wasNotDone){const sv=p.score_value||5;xpPop(sv);confetti(35);}toast(ns==='done'?'✓ Bajarildi':'Belgilash olindi');scheduleStatsRefresh(true);}catch(err){const m=String(err&&err.message||'');if(m.includes('409'))toast('⏰ Bu rejani hozir o\'zgartirib bo\'lmaydi',true);else toast('Xato!',true);}};row.querySelector('[data-act="edit"]').onclick=e=>{e.stopPropagation();const p=State.plans.find(x=>x.id===id);if(p)openPlanModal(p);};row.querySelector('[data-act="del"]').onclick=async e=>{e.stopPropagation();const p=State.plans.find(x=>x.id===id);if(p&&planBlockReason(p)==='past'){toast('⏰ O\'tib ketgan kun rejasini o\'chirib bo\'lmaydi',true);return;}if(!await confirmDialog({title:'Rejani o\'chirish',message:'Bu rejani o\'chirishni xohlaysizmi?'}))return;try{await apiPlanDelete(id);State.plans=State.plans.filter(x=>x.id!==id);renderPlans();renderHero();toast('🗑 O\'chirildi');}catch(err){const m=String(err&&err.message||'');if(m.includes('409'))toast('⏰ O\'tib ketgan kun rejasini o\'chirib bo\'lmaydi',true);else toast('Xato!',true);}};});}

function renderGoalsView(){
  // Faqat Yillik va Oylik maqsadlar qoldi. Eski (yashirilgan) turlar yashamaydi.
  if(State.goalPeriod!=='yearly'&&State.goalPeriod!=='monthly')State.goalPeriod='yearly';
  document.getElementById('gvYearly').classList.toggle('hidden',State.goalPeriod!=='yearly');
  document.getElementById('gvMonthly').classList.toggle('hidden',State.goalPeriod!=='monthly');
  if(State.goalPeriod==='yearly')renderYearly();else renderMonthly();
}

const goalsBy=(t,p)=>State.goals.filter(g=>g.goal_type===t&&(!p||g.period===p));

function renderYearly(){const g=document.getElementById('yearChips');const cur=new Date().getFullYear();const ys=[];for(let y=cur+3;y>=cur-3;y--)ys.push(y);g.innerHTML=ys.map(y=>{const c=goalsBy('yearly',String(y)).length;const sel=State.selectedYear===y;return `<div class="year-chip ${sel?'active':''}" data-year="${y}"><div class="y">${y}</div><div class="c">${c} maqsad</div></div>`;}).join('');g.querySelectorAll('.year-chip').forEach(c=>c.onclick=()=>{State.selectedYear=+c.dataset.year;renderYearly();});renderYearlyList();}
function renderYearlyList(){const l=goalsBy('yearly',String(State.selectedYear));document.getElementById('yearlyList').innerHTML=renderGoalList(l,State.selectedYear+'-yil uchun maqsadlar');bindGoalActions('yearlyList');}

function renderMonthly(){const g=document.getElementById('monthsGrid');const cM=new Date().getMonth(),cY=new Date().getFullYear();g.innerHTML=UZ_MONTHS.map((m,i)=>{const k=State.selectedYear+'-'+pad(i+1);const c=goalsBy('monthly',k).length;const ic=i===cM&&State.selectedYear===cY;const sel=State.selectedMonth===i;return `<div class="month-cell ${ic?'current':''}" data-m="${i}" style="${sel?'border-color:var(--primary);background:var(--primary-soft)':''}"><div class="mn">${UZ_MONTHS_SHORT[i]}</div><div class="ct">${c}</div>${c?'<div class="dot"></div>':''}</div>`;}).join('');g.querySelectorAll('.month-cell').forEach(c=>c.onclick=()=>{State.selectedMonth=+c.dataset.m;renderMonthly();});renderMonthlyList();}
function renderMonthlyList(){const k=State.selectedYear+'-'+pad(State.selectedMonth+1);const l=goalsBy('monthly',k);document.getElementById('monthlyList').innerHTML=renderGoalList(l,UZ_MONTHS[State.selectedMonth]+' '+State.selectedYear+' maqsadlari');bindGoalActions('monthlyList');}

// renderWeekly / renderDaily / renderDiary / renderCalendar / openDayModal /
// renderDailyList olib tashlandi — kunlik va haftalik maqsad turlari yo'q.
// Takroriy niyatlar Odat (Habit)'ga, bir martalik ishlar Reja (Plan)'ga ko'chirilgan.











function renderGoalList(list,emp){if(!list.length)return emptyState('🎯',emp||'Hech narsa yo\'q','+ tugma orqali yangi maqsad qo\'shing');return list.map((g,i)=>`<div class="goal ${g.completed?'done':''}" style="animation-delay:${i*50}ms" data-id="${g.id}"><div class="cbx ${g.completed?'done':''}" data-act="toggle">${g.completed?'✓':''}</div><div class="body"><div class="ttl">${esc(g.title)}</div>${g.description?`<div class="desc">${esc(g.description)}</div>`:''}</div><button class="del" data-act="edit" aria-label="Tahrirlash" style="color:var(--text-3)"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M12 20h9M16.5 3.5a2.121 2.121 0 1 1 3 3L7 19l-4 1 1-4z"/></svg></button><button class="del" data-act="delete" aria-label="O'chirish"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M3 6h18M19 6l-2 14H7L5 6m5 4v6m4-6v6M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/></svg></button></div>`).join('');}

function bindGoalActions(cid){const w=document.getElementById(cid);w.querySelectorAll('.goal').forEach(row=>{const id=+row.dataset.id;row.querySelector('[data-act="toggle"]').onclick=async e=>{e.stopPropagation();const g=State.goals.find(x=>x.id===id);if(!g)return;const nv=!g.completed;if(nv&&isGoalPeriodFuture(g.goal_type,g.period)){toast('⏰ Bu maqsad davri hali boshlanmagan',true);return;}g.completed=nv;row.classList.toggle('done',nv);row.querySelector('.cbx').classList.toggle('done',nv);row.querySelector('.cbx').textContent=nv?'✓':'';if(nv){xpPop(5);confetti(35);try{tg?.HapticFeedback?.notificationOccurred?.('success');}catch(_){}}try{await apiGoalUpdate(id,{completed:nv});toast(nv?'✓ Bajarildi':'Belgilash olindi');}catch(err){g.completed=!nv;row.classList.toggle('done',!nv);row.querySelector('.cbx').classList.toggle('done',!nv);row.querySelector('.cbx').textContent=!nv?'✓':'';const m=String(err&&err.message||'');if(m.includes('409'))toast('⏰ Bu maqsad davri hali boshlanmagan',true);else toast('Xato!',true);}};const eb=row.querySelector('[data-act="edit"]');if(eb)eb.onclick=e=>{e.stopPropagation();const g=State.goals.find(x=>x.id===id);if(g)openModal(g.goal_type,g.period,g);};row.querySelector('[data-act="delete"]').onclick=async e=>{e.stopPropagation();if(!await confirmDialog({title:'Maqsadni o\'chirish',message:'Bu maqsadni o\'chirishni xohlaysizmi?'}))return;try{await apiGoalDelete(id);State.goals=State.goals.filter(x=>x.id!==id);renderGoalsView();toast('🗑 O\'chirildi');}catch(_){toast('Xato!',true);}};});}

// Maqsad davri o'tib ketganmi? (frontend tekshiruvi — backend bilan bir xil mantiq)
function isGoalPeriodPast(goalType,period){try{const now=new Date();const p=String(period||'').trim();if(!p)return false;const gt=(goalType||'').toLowerCase();if(gt==='yearly')return parseInt(p,10)<now.getFullYear();if(gt==='monthly'){const[y,m]=p.split('-').map(n=>parseInt(n,10));return(y<now.getFullYear())||(y===now.getFullYear()&&m<(now.getMonth()+1));}return false;}catch(_){return false;}}

// Maqsad davri hali BOSHLANMAGANmi? (kelajakdagi maqsadni bajarib bo'lmaydi)
function isGoalPeriodFuture(goalType,period){try{const now=new Date();const p=String(period||'').trim();if(!p)return false;const gt=(goalType||'').toLowerCase();if(gt==='yearly')return parseInt(p,10)>now.getFullYear();if(gt==='monthly'){const[y,m]=p.split('-').map(n=>parseInt(n,10));return(y>now.getFullYear())||(y===now.getFullYear()&&m>(now.getMonth()+1));}return false;}catch(_){return false;}}

// Rejani 'bajarildi' deb belgilashga to'siq: '' (yo'q) / 'past' / 'future'
//  • kechagi/oldingi kun -> 'past'  • bugun vaqti kelmagan / kelajak kun -> 'future'
//  • bugun vaqti kelgan / vaqtsiz -> '' (mumkin)
function planBlockReason(p){try{const now=new Date();const todayStr=ymd(now);const pd=p&&p.plan_date?String(p.plan_date):'';if(!pd)return '';if(pd<todayStr)return 'past';if(pd>todayStr)return 'future';const t=p.scheduled_time;if(!t)return '';const m=/^(\d{1,2}):(\d{2})/.exec(String(t));if(!m)return '';const due=new Date(now);due.setHours(parseInt(m[1],10),parseInt(m[2],10),0,0);return now>=due?'':'future';}catch(_){return '';}}

function moveGoalSegInd(){const ind=document.getElementById('goalSegInd');const a=document.querySelector('#goalSeg .seg-item.active');if(!a)return;ind.style.left=a.offsetLeft+'px';ind.style.width=a.offsetWidth+'px';}

async function renderStats(){
  await loadPlansRange();
  const PR=State.plansRange.length?State.plansRange:State.plans;
  const tod=new Date();
  // Haftalik faollik chizig'i: FAQAT bajarilgan rejalar (kunlik maqsad tushunchasi olib tashlandi).
  const bars=[];
  for(let i=6;i>=0;i--){
    const d=addDays(tod,-i);const k=ymd(d);
    const c=PR.filter(p=>p.plan_date===k&&p.status==='done').length;
    bars.push({d,cnt:c});
  }
  const mx=Math.max(1,...bars.map(b=>b.cnt));
  document.getElementById('weekBars').innerHTML=bars.map(b=>`<div class="bar-col"><div class="bar" data-v="${b.cnt}" style="height:0px"></div><div class="lb">${UZ_DOW_SHORT[(b.d.getDay()+6)%7]}</div></div>`).join('');
  setTimeout(()=>{document.querySelectorAll('#weekBars .bar').forEach((bar,i)=>{const h=Math.max(6,(bars[i].cnt/mx)*110);bar.style.height=h+'px';});},100);
  renderTrend(30);

  const heat=document.getElementById('heatGrid');
  const cells=[];
  for(let i=0;i<98;i++){const d=addDays(tod,-(97-i));const c=PR.filter(p=>p.plan_date===ymd(d)&&p.status==='done').length;const l=c===0?0:c<2?1:c<4?2:c<6?3:4;cells.push(`<div class="heat-cell" data-l="${l}" title="${ymd(d)}: ${c}"></div>`);}
  heat.innerHTML=cells.join('');

  // Maqsadlar donut + Yillik/Oylik bo'yicha taqsimot (faqat 2 tur qoldi).
  const aG=State.goals;const dG=aG.filter(g=>g.completed).length;const pct=aG.length?Math.round(dG*100/aG.length):0;
  document.getElementById('goalDonutPill').textContent=pct+'%';
  const C=2*Math.PI*46;
  setTimeout(()=>{document.getElementById('donut').setAttribute('stroke-dashoffset',String(C*(1-pct/100)));},200);
  const types=['yearly','monthly'];const labels=['Yillik','Oylik'];
  document.getElementById('goalBreakdown').innerHTML=types.map((t,i)=>{const tot=State.goals.filter(g=>g.goal_type===t).length;const dn=State.goals.filter(g=>g.goal_type===t&&g.completed).length;const p=tot?Math.round(dn*100/tot):0;return `<div style="display:flex;align-items:center;gap:8px;font-size:11.5px"><span style="width:60px;color:var(--text-2);font-weight:600">${labels[i]}</span><div style="flex:1;height:6px;background:var(--border);border-radius:999px;overflow:hidden"><div style="width:${p}%;height:100%;background:var(--grad);border-radius:999px;transition:width 1s ease"></div></div><span style="font-weight:700;color:var(--primary);min-width:38px;text-align:right">${dn}/${tot}</span></div>`;}).join('');

  renderHistory();
  document.getElementById('stStreakDelta').textContent=Math.min(7,State.user?.streak||0);
  document.getElementById('stTotalDelta').textContent=PR.filter(p=>p.status==='done'&&new Date(p.plan_date)>=addDays(tod,-7)).reduce((s,p)=>s+(p.score_value||0),0);
  renderExtraStats(PR);
}

function renderExtraStats(PR){const el=document.getElementById('extraStats');if(!el)return;const tot=PR.length;const dn=PR.filter(p=>p.status==='done').length;const rate=tot?Math.round(dn*100/tot):0;const byDay={};PR.forEach(p=>{if(p.status==='done'){byDay[p.plan_date]=(byDay[p.plan_date]||0)+(p.score_value||0);}});const days=Object.keys(byDay);let best={d:'—',v:0};days.forEach(k=>{if(byDay[k]>best.v)best={d:k,v:byDay[k]};});const avg=days.length?Math.round(days.reduce((s,k)=>s+byDay[k],0)/days.length):0;const bestLabel=best.d!=='—'?new Date(best.d+'T00:00:00').getDate()+' '+UZ_MONTHS_SHORT[new Date(best.d+'T00:00:00').getMonth()]:'—';el.innerHTML=`<div class="stat-card"><div class="ic-bg">📈</div><div class="l">Bajarish %</div><div class="v">${rate}%</div><div class="ch">${dn}/${tot} reja (30 kun)</div></div><div class="stat-card"><div class="ic-bg">⚡</div><div class="l">O'rtacha ball</div><div class="v">${avg}</div><div class="ch">Kuniga</div></div><div class="stat-card"><div class="ic-bg">🏅</div><div class="l">Eng yaxshi kun</div><div class="v" style="font-size:18px">${bestLabel}</div><div class="ch">+${best.v} ball</div></div><div class="stat-card"><div class="ic-bg">📅</div><div class="l">Faol kunlar</div><div class="v">${days.length}</div><div class="ch">30 kun ichida</div></div>`;}

function renderTrend(days){const PR=State.plansRange.length?State.plansRange:State.plans;const HB=State.habits||[];const tod=new Date();const pts=[];for(let i=days-1;i>=0;i--){const d=addDays(tod,-i);const k=ymd(d);const planSc=PR.filter(p=>p.plan_date===k&&p.status==='done').reduce((s,p)=>s+(p.score_value||0),0);const habitSc=HB.reduce((s,h)=>s+(((h.log_dates||[]).indexOf(k)>=0)?HABIT_SCORE:0),0);pts.push(planSc+habitSc);}const W=320,H=160,P=8;const mx=Math.max(...pts,1);const step=(W-P*2)/(pts.length-1);const points=pts.map((v,i)=>[P+i*step,H-P-(v/mx)*(H-P*2)]);let line='M '+points[0][0].toFixed(1)+' '+points[0][1].toFixed(1);for(let i=1;i<points.length;i++){const x0=points[i-1][0],y0=points[i-1][1],x1=points[i][0],y1=points[i][1];const cx=(x0+x1)/2;line+=' C '+cx.toFixed(1)+' '+y0.toFixed(1)+', '+cx.toFixed(1)+' '+y1.toFixed(1)+', '+x1.toFixed(1)+' '+y1.toFixed(1);}const area=line+' L '+points[points.length-1][0].toFixed(1)+' '+H+' L '+points[0][0].toFixed(1)+' '+H+' Z';document.getElementById('trendG').innerHTML='<path class="area-path" d="'+area+'"/><path class="area-line" d="'+line+'"/>'+points.map((p,i)=>i%Math.ceil(points.length/6)===0||i===points.length-1?'<circle class="area-dot" cx="'+p[0].toFixed(1)+'" cy="'+p[1].toFixed(1)+'" r="3"/>':'').join('');}

function renderAchs(){const st=State.user?.streak||0;const sc=State.user?.total_score||0;const dn=State.goals.filter(g=>g.completed).length+State.plans.filter(p=>p.status==='done').length;const list=[{ic:'🔥',nm:'Olov',ds:'3 kun streak',un:st>=3},{ic:'⚡',nm:'Yashin',ds:'7 kun streak',un:st>=7},{ic:'💎',nm:'Olmos',ds:'30 kun streak',un:st>=30},{ic:'🎯',nm:'Aniq',ds:'10 maqsad',un:dn>=10},{ic:'🏆',nm:'Chempion',ds:'100 ball',un:sc>=100},{ic:'👑',nm:'Qirol',ds:'500 ball',un:sc>=500}];document.getElementById('achs').innerHTML=list.map(a=>`<div class="ach ${a.un?'':'locked'}"><div class="ic">${a.ic}</div><div class="nm">${a.nm}</div><div class="ds">${a.ds}</div></div>`).join('');}

// Bajarilgan rejalar tarixi — har kun uchun to'ladigan chiziq + bajarilgan/jami
async function renderHistory(){const el=document.getElementById('histList');if(!el)return;let days=[];try{const r=await api('/api/webapp/history');days=r.days||[];}catch(e){console.warn('history',e);}if(!days.length){el.innerHTML=emptyState('📋','Hali tarix yo\'q','Reja qo\'shib, bajara boshlang');return;}const todayStr=ymd(new Date());const yStr=ymd(addDays(new Date(),-1));el.innerHTML=days.map(d=>{const pct=d.total?Math.round(d.done*100/d.total):0;let label;if(d.date===todayStr)label='Bugun';else if(d.date===yStr)label='Kecha';else{const dt=new Date(d.date+'T00:00:00');label=dt.getDate()+' '+UZ_MONTHS_SHORT[dt.getMonth()];}const full=pct>=100?'full':'';const zero=d.done===0?'zero':'';return `<div class="hist-row ${zero}"><span class="hl">${esc(label)}</span><div class="hbar ${full}"><i data-w="${pct}"></i></div><span class="hv">${d.done}/${d.total}</span></div>`;}).join('');setTimeout(()=>{el.querySelectorAll('.hbar>i').forEach(b=>{b.style.width=(b.dataset.w||0)+'%';});},60);}

const THEMES=[{k:'default',n:'Asl holat',g:'linear-gradient(135deg,#14b8a6,#06b6d4)'},{k:'sprout',n:'Sprout',g:'linear-gradient(135deg,#22c55e,#84cc16)'},{k:'spectrum',n:'Spectrum',g:'linear-gradient(135deg,#f43f5e,#8b5cf6,#06b6d4)'},{k:'gamma',n:'Gamma',g:'linear-gradient(135deg,#a855f7,#7c3aed)'},{k:'atmosphere',n:'Atmosphere',g:'linear-gradient(135deg,#0ea5e9,#6366f1)'},{k:'gold',n:'Gold Leaf',g:'linear-gradient(135deg,#f5d76e,#d4a017)'}];
// Tema tanlash — faqat Premium foydalanuvchilar uchun.
// Bepul foydalanuvchi tugmani bosa, temani o'zgartirmaymiz va paywall'ni ochamiz.
// (Faol tema (State.theme) old-oldindan localStorage'dan yuklanadi, shuning uchun
// bepul foydalanuvchi hech bo'lmaganda default temani ko'rishi mumkin.)
function renderThemes(){
  const g=document.getElementById('themeGrid');
  if(!g)return;
  const isPremium=!!(State.sub&&State.sub.is_premium);
  g.innerHTML=THEMES.map(t=>`<div class="theme-tile ${State.theme===t.k?'active':''}${isPremium?'':' locked'}" data-th="${t.k}"><div class="sw" style="background:${t.g}"></div><div class="nm">${t.n}${isPremium?'':' 🔒'}</div></div>`).join('');
  g.querySelectorAll('.theme-tile').forEach(t=>t.onclick=()=>{
    if(!(State.sub&&State.sub.is_premium)){
      // Premium yo'q — tema o'zgartirmaymiz. Faqat qisqa xabar ko'rsatamiz;
      // paywall'ga o'tkazMAYMIZ (foydalanuvchi tanlovi buzilmasin).
      try{tg?.HapticFeedback?.notificationOccurred?.('warning');}catch(_){}
      toast('🎨 Temani o\'zgartirish faqat Premium foydalanuvchilar uchun',true);
      return;
    }
    State.theme=t.dataset.th;
    document.documentElement.setAttribute('data-theme',State.theme);
    localStorage.setItem('iz_theme',State.theme);
    renderThemes();
    toast('🎨 Tema o\'zgartirildi');
    if(document.querySelector('.page[data-page="stats"]').classList.contains('active'))renderStats();
  });
}

function applyMode(){document.documentElement.setAttribute('data-mode',State.mode);document.getElementById('darkToggle').classList.toggle('on',State.mode==='dark');document.getElementById('modeIcon').textContent=State.mode==='dark'?'🌙':'☀️';}

const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const setText=(id,val)=>{const el=document.getElementById(id);if(el)el.textContent=val;};
const emptyState=(ic,t,p)=>`<div class="empty-state"><div class="ico">${ic}</div><h4>${esc(t)}</h4><p>${esc(p)}</p></div>`;
function toast(msg,danger){const el=document.getElementById('toast');if(!el)return;el.textContent=msg;el.style.background=danger?'var(--danger)':'';el.style.color=danger?'#fff':'';el.classList.add('show');clearTimeout(el._t);el._t=setTimeout(()=>el.classList.remove('show'),2000);}

// Maxsus tasdiqlash oynasi (domen nomli native confirm o'rniga).
// Qo'llab-quvvatlanadigan `opts`:
//   icon, title, message, okText, cancelText
//   okKind: 'danger' (default) | 'premium'
//     - 'danger' — qizil "O'chirish" tugmasi (default xatti-harakat)
//     - 'premium' — gradient rangdagi Premium CTA (icon ham primary rangda)
function confirmDialog(opts){
  opts=opts||{};
  return new Promise(resolve=>{
    const back=document.getElementById('confirmBack');
    if(!back){resolve(true);return;}
    const kind=opts.okKind||'danger';
    setText('confirmIc',opts.icon||'🗑');
    setText('confirmTtl',opts.title||'O\'chirilsinmi?');
    setText('confirmMsg',opts.message||'Bu amalni qaytarib bo\'lmaydi.');
    const okBtn=document.getElementById('confirmOk');
    const cancelBtn=document.getElementById('confirmCancel');
    const icEl=document.getElementById('confirmIc');
    if(okBtn){
      okBtn.textContent=opts.okText||'O\'chirish';
      okBtn.classList.remove('kind-danger','kind-premium');
      okBtn.classList.add('kind-'+kind);
    }
    if(icEl){
      icEl.classList.remove('kind-danger','kind-premium');
      icEl.classList.add('kind-'+kind);
    }
    if(cancelBtn)cancelBtn.textContent=opts.cancelText||'Bekor';
    back.classList.add('show');
    const done=val=>{back.classList.remove('show');if(okBtn)okBtn.onclick=null;if(cancelBtn)cancelBtn.onclick=null;back.onclick=null;resolve(val);};
    if(okBtn)okBtn.onclick=()=>{try{tg?.HapticFeedback?.impactOccurred('medium');}catch(_){}done(true);};
    if(cancelBtn)cancelBtn.onclick=()=>done(false);
    back.onclick=e=>{if(e.target===back)done(false);};
  });
}

// Premium kerakligi haqidagi inline dialog. Foydalanuvchi biror gated
// bo'limga (Do'stlar/Statistika/Reja qo'shish/... /AI) kirishga uringanida
// chaqiriladi. Sahifa navigatsiyasi qilinmaydi — dialog joyida ochiladi:
//   • "💎 Premium olish" bosilsa → paywall ochiladi
//   • "Orqaga" bosilsa → oddiy yopiladi
//
// Chaqiruvchi kod bu funksiyani MUAMMOLI amaldan OLDIN chaqirib,
// State.sub.is_premium=false bo'lsa navigatsiya/actionni bekor qilishi kerak.
// True qaytsa: foydalanuvchi paywall'ni ochishga bosdi. False: yopdi.
async function premiumRequiredDialog(opts){
  opts=opts||{};
  const ok=await confirmDialog({
    icon:opts.icon||'💎',
    title:opts.title||'Faqat Premium foydalanuvchilar uchun',
    message:opts.message||'Bu bo\'limdan foydalanish uchun Premium olishingiz kerak.',
    okText:'💎 Premium olish',
    cancelText:'Orqaga',
    okKind:'premium',
  });
  if(ok){
    openPaywall();
    return true;
  }
  return false;
}

// Yordamchi: agar bepul foydalanuvchi bo'lsa, dialogni ochib true qaytaradi
// (chaqiruvchi kod amaldan chiqishi kerak); premium bo'lsa false — davom eting.
function premiumGate(sectionMeta){
  if(State.sub&&State.sub.is_premium)return false;
  premiumRequiredDialog(sectionMeta||{});
  return true;
}

function openModal(period,periodKey,goal){
  // Eski (yashirilgan) `weekly`/`daily` yozuvlarni tahrirlashga urinilsa —
  // avtomatik yillikga tushamiz (foydalanuvchi bunday maqsadni ko'rmaydi
  // ham, lekin himoya sifatida).
  if(period!=='yearly'&&period!=='monthly'){period='yearly';periodKey=String(new Date().getFullYear());}
  State.modal={period,periodKey,id:goal?goal.id:null};
  const lb={yearly:'yillik',monthly:'oylik'};
  document.getElementById('modalTitle').textContent=(goal?'Tahrirlash: ':'Yangi ')+lb[period]+' maqsad';
  document.getElementById('mTitle').value=goal?goal.title:'';
  document.getElementById('mDesc').value=goal?goal.description||'':'';
  // Davr tanlash — faqat foydalanuvchining o'z maqsadi uchun. A'zolar bir-
  // biriga maqsad qo'sha olmaydi (talab bo'yicha), shu sabab bu yerda oldingi
  // "isMemberCreate" oqimi olib tashlandi.
  _setupModalPeriodPicker(false, period, periodKey);
  document.getElementById('modalBack').classList.add('show');
  setTimeout(()=>document.getElementById('mTitle').focus(),300);
}

// Modal ichidagi davr tanlash (Yillik/Oylik + yil + oy). Faqat a'zo uchun
// yangi maqsad yaratayotganda ko'rinadi — o'zi uchun yaratishda Maqsadlar
// sahifasidagi chiplar allaqachon davrni belgilagan bo'ladi.
function _setupModalPeriodPicker(visible, initialType, initialKey){
  const pick=document.getElementById('mPeriodPicker');
  const row=document.getElementById('mPeriodYMRow');
  if(!pick||!row)return;
  if(!visible){pick.style.display='none';row.style.display='none';return;}
  pick.style.display='';row.style.display='';

  // Yil dropdown — joriy yildan -3 dan +10 yilgacha (kelajak ham).
  const yearSel=document.getElementById('mYear');
  const monthSel=document.getElementById('mMonth');
  const curY=new Date().getFullYear();
  if(yearSel && !yearSel.dataset.built){
    let opts='';
    for(let y=curY-3;y<=curY+10;y++)opts+=`<option value="${y}">${y}</option>`;
    yearSel.innerHTML=opts;
    yearSel.dataset.built='1';
  }
  if(monthSel && !monthSel.dataset.built){
    let opts='';
    for(let i=0;i<12;i++)opts+=`<option value="${pad(i+1)}">${UZ_MONTHS[i]}</option>`;
    monthSel.innerHTML=opts;
    monthSel.dataset.built='1';
  }

  // Boshlang'ich qiymatlar — chaqirilgan davrdan olamiz.
  let type=initialType==='monthly'?'monthly':'yearly';
  let y=curY, m=(new Date().getMonth()+1);
  try{
    if(type==='yearly' && initialKey){y=parseInt(String(initialKey),10)||curY;}
    else if(type==='monthly' && initialKey){
      const [yy,mm]=String(initialKey).split('-').map(n=>parseInt(n,10));
      if(yy)y=yy; if(mm)m=mm;
    }
  }catch(_){}
  if(yearSel)yearSel.value=String(y);
  if(monthSel)monthSel.value=pad(m);

  // Type seg
  document.querySelectorAll('#mPeriodTypeSeg .seg-item').forEach(it=>{
    it.classList.toggle('active', it.dataset.mpt===type);
    it.onclick=()=>{
      document.querySelectorAll('#mPeriodTypeSeg .seg-item').forEach(x=>x.classList.remove('active'));
      it.classList.add('active');
      _syncModalMonthVisibility();
      _moveModalTypeInd();
    };
  });
  _syncModalMonthVisibility();
  requestAnimationFrame(_moveModalTypeInd);
}
function _syncModalMonthVisibility(){
  const t=document.querySelector('#mPeriodTypeSeg .seg-item.active');
  const type=t?t.dataset.mpt:'yearly';
  const monthFld=document.getElementById('mMonthFld');
  if(monthFld)monthFld.style.display=(type==='monthly')?'':'none';
}
function _moveModalTypeInd(){
  const ind=document.getElementById('mPeriodTypeInd');
  const a=document.querySelector('#mPeriodTypeSeg .seg-item.active');
  if(!ind||!a)return;
  ind.style.left=a.offsetLeft+'px';
  ind.style.width=a.offsetWidth+'px';
}
// Modaldan tanlangan davrni o'qib qaytaradi: {goal_type, period}
function _readModalPeriod(){
  const t=document.querySelector('#mPeriodTypeSeg .seg-item.active');
  const type=t?t.dataset.mpt:'yearly';
  const y=document.getElementById('mYear')?.value||String(new Date().getFullYear());
  const m=document.getElementById('mMonth')?.value||pad(new Date().getMonth()+1);
  return {goal_type:type, period:(type==='yearly')?y:(y+'-'+m)};
}
function closeModal(){
  document.getElementById('modalBack').classList.remove('show');
  State.forMemberContext=null;
}
async function saveModal(){
  const t=document.getElementById('mTitle').value.trim();
  if(!t){toast('Sarlavha bo\'sh',true);return;}
  const d=document.getElementById('mDesc').value.trim();
  const isEdit=!!State.modal.id;
  // Eslatma: a'zolar bir-biriga maqsad qo'sha olmaydi (talab bo'yicha).
  // Shu sabab bu yerda forMemberContext bo'lsa ham oqim faqat o'z maqsadiga
  // yozadi. Boshqa a'zoga faqat reja va odat qo'shsa bo'ladi.
  if(!isEdit && State.forMemberContext){
    State.forMemberContext=null; // xavfsizlik uchun tozalaymiz
  }
  try{
    if(isEdit){
      const ng=await apiGoalUpdate(State.modal.id,{title:t,description:d||null});
      const idx=State.goals.findIndex(g=>g.id===State.modal.id);
      if(idx>=0)State.goals[idx]={...State.goals[idx],...ng};
      toast('✓ Yangilandi');
    }else{
      const pl={title:t,description:d||null,goal_type:State.modal.period,period:State.modal.periodKey};
      const ng=await apiGoalCreate(pl);
      State.goals.push(ng);
      toast('✨ Maqsad qo\'shildi');
    }
    closeModal();renderGoalsView();setText('msGoals',State.goals.length);
  }catch(e){toast('Xato: '+e.message,true);}
}

function fillTimeSelects(){
  const h=document.getElementById('pHour');const m=document.getElementById('pMin');
  if(h&&!h.options.length){let o='<option value="">—</option>';for(let i=0;i<24;i++)o+='<option value="'+pad(i)+'">'+pad(i)+'</option>';h.innerHTML=o;}
  if(m&&!m.options.length){let o='';for(let i=0;i<60;i+=5)o+='<option value="'+pad(i)+'">'+pad(i)+'</option>';m.innerHTML=o;}
}
function fillTimeSelectsFor(hId,mId){
  const h=document.getElementById(hId);const m=document.getElementById(mId);
  if(h&&!h.options.length){let o='';for(let i=0;i<24;i++)o+='<option value="'+pad(i)+'">'+pad(i)+'</option>';h.innerHTML=o;}
  if(m&&!m.options.length){let o='';for(let i=0;i<60;i+=5)o+='<option value="'+pad(i)+'">'+pad(i)+'</option>';m.innerHTML=o;}
}
function openPlanModal(plan){
  State.planModal={id:plan?plan.id:null};
  fillTimeSelects();
  setText('planModalTitle',plan?'Rejani tahrirlash':'Yangi reja');
  const elT=document.getElementById('pTitle');if(elT)elT.value=plan?.title||'';
  const elD=document.getElementById('pDesc');if(elD)elD.value=plan?.description||'';
  // Vaqtni 24h tanlagichga joylash
  let hh='',mm='00';
  if(plan&&plan.scheduled_time&&plan.scheduled_time.includes(':')){const pp=plan.scheduled_time.split(':');hh=pad(parseInt(pp[0],10)||0);const mi=parseInt(pp[1],10)||0;mm=pad(Math.round(mi/5)*5%60);}
  const hSel=document.getElementById('pHour');if(hSel)hSel.value=hh;
  const mSel=document.getElementById('pMin');if(mSel)mSel.value=mm;
  // Sana: tahrirda reja sanasi, yangi rejada tanlangan kun (o'tgan kun emas)
  const dEl=document.getElementById('pDate');
  if(dEl){
    const todayStr=ymd(new Date());
    if(plan&&plan.plan_date){
      dEl.value=plan.plan_date;dEl.removeAttribute('min');
    }else{
      const sel=ymd(State.selectedDate||new Date());
      dEl.value=(sel<todayStr)?todayStr:sel;
      dEl.min=todayStr;  // yangi rejada o'tib ketgan kun tanlab bo'lmaydi
    }
  }
  const back=document.getElementById('planModalBack');if(back)back.classList.add('show');
  setTimeout(()=>{const f=document.getElementById('pTitle');if(f)f.focus();},300);
}
function closePlanModal(){
  const b=document.getElementById('planModalBack');if(b)b.classList.remove('show');
  // Do'stlar konteksti — modal yopilsa (cancel/backdrop) tozalanadi.
  State.forMemberContext=null;
}
async function savePlanModal(){
  const t=(document.getElementById('pTitle')?.value||'').trim();
  if(!t){toast('Sarlavha bo\'sh',true);return;}
  const desc=(document.getElementById('pDesc')?.value||'').trim();
  const hh=document.getElementById('pHour')?.value||'';
  const mm=document.getElementById('pMin')?.value||'00';
  if(!hh){
    toast('⏰ Iltimos, eslatma vaqtini belgilang',true);
    const hSel=document.getElementById('pHour');
    if(hSel){hSel.classList.add('field-error');hSel.focus();try{hSel.scrollIntoView({block:'center',behavior:'smooth'});}catch(_){}setTimeout(()=>hSel.classList.remove('field-error'),1600);}
    return;
  }
  const tm=hh+':'+mm;
  const dt=document.getElementById('pDate')?.value||ymd(State.selectedDate||new Date());
  const body={title:t,description:desc||null,scheduled_time:tm,plan_date:dt};
  const isEdit=!!State.planModal.id;
  if(!isEdit && dt < ymd(new Date())){toast('⏰ O\'tib ketgan kun uchun reja qo\'shib bo\'lmaydi',true);return;}
  // ── Boshqa a'zo uchun yaratish (Do'stlar guruhi) ──
  if(!isEdit && State.forMemberContext){
    const ctx=State.forMemberContext;
    try{
      await apiForMemberPlan(ctx.groupId, ctx.userId, body);
    }catch(e){
      const msg=String(e&&e.message||'');
      if(msg.includes('402')){toast('⚠️ A\'zoning bepul kunlik limiti tugagan',true);return;}
      if(msg.includes('403')){toast('🛡 A\'zo sizga ruxsat bermagan',true);return;}
      if(msg.includes('409')){toast('⏰ O\'tib ketgan kun uchun reja qo\'shib bo\'lmaydi',true);return;}
      toast('Xato: '+msg,true);return;
    }
    State.forMemberContext=null;
    closePlanModal();
    toast('✨ '+ctx.name+' uchun reja qo\'shildi');
    try{await openMember(ctx.userId);}catch(_){}
    return;
  }
  try{
    if(isEdit){const np=await apiPlanUpdate(State.planModal.id,body);const idx=State.plans.findIndex(x=>x.id===State.planModal.id);if(idx>=0)State.plans[idx]=np;}
    else{await apiPlanCreate(body);}
  }catch(e){
    const msg=String(e&&e.message||'');
    if(msg.includes('402')){closePlanModal();return;/* Premium dialog global api() da avtomatik ochiladi */}
    if(msg.includes('409')){toast('⏰ O\'tib ketgan kun uchun reja qo\'shib bo\'lmaydi',true);return;}
    toast('Xato: '+msg,true);return;
  }
  // Saqlash muvaffaqiyatli — endi UI ni yangilaymiz (bu yerdagi xato saqlashga ta'sir qilmaydi)
  closePlanModal();
  toast(isEdit?'✓ Yangilandi':'✨ Reja qo\'shildi');
  try{
    await loadPlansForSelectedDay();
    loadSnapshot();loadQuest();
  }catch(err){console.warn('post-save refresh',err);}
}

function fabAction(){
  const ap=document.querySelector('.page.active').dataset.page;
  if(ap==='home'){openPlanModal(null);return;}
  if(ap==='goals'){
    const gp=(State.goalPeriod==='monthly')?'monthly':'yearly';
    const pk=(gp==='yearly')?String(State.selectedYear):(State.selectedYear+'-'+pad(State.selectedMonth+1));
    openModal(gp,pk);
    return;
  }
}

function updateFabVisibility(){/* inline add buttons now live inside sections */}

// ═══════════════════════════════════════════════════════════════
// DO'STLAR (Friends) — render + wiring
// ═══════════════════════════════════════════════════════════════
function _showFriendsView(v){
  State.friendsView=v;
  document.getElementById('friendsListView').classList.toggle('hidden',v!=='list');
  document.getElementById('friendsGroupView').classList.toggle('hidden',v!=='group');
  document.getElementById('friendsMemberView').classList.toggle('hidden',v!=='member');
}

async function loadGroupsAPI(){
  try{const d=await apiGroupsList();State.groups=d.groups||[];}
  catch(e){console.warn('groups',e);State.groups=[];}
  renderGroupsList();
}

function renderGroupsList(){
  _showFriendsView('list');
  const el=document.getElementById('friendsGroupsList');
  if(!el)return;
  if(!State.groups.length){
    el.innerHTML=emptyState('👥','Hozircha guruh yo\'q','Yangi guruh yarating va do\'stlaringizni taklif qiling');
    return;
  }
  el.innerHTML=State.groups.map(g=>`
    <div class="grp-card" data-gid="${g.id}">
      <div class="ic">👥</div>
      <div class="body">
        <div class="nm">${esc(g.name)} ${g.is_owner?'<span class="badge-owner">EGA</span>':''}</div>
        <div class="sub">${g.member_count} a'zo${g.description?' · '+esc(g.description):''}</div>
      </div>
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" style="color:var(--text-3)"><polyline points="9 6 15 12 9 18"/></svg>
    </div>`).join('');
  el.querySelectorAll('.grp-card').forEach(c=>c.onclick=()=>openGroup(+c.dataset.gid));
}

async function openGroup(gid){
  let d;try{d=await apiGroupGet(gid);}catch(e){toast('Guruh yuklanmadi',true);return;}
  State.currentGroup=d;
  _showFriendsView('group');
  document.getElementById('friendsGroupName').textContent=d.name;
  document.getElementById('friendsGroupSub').textContent=(d.members||[]).length+' a\'zo · kod: '+d.invite_code;
  // Sozlamalar tugmasi HAMMAGA ko'rinadi:
  //   • Ega — tahrirlash / o'chirish (ega chiqolmaydi)
  //   • A'zo — guruhdan chiqish
  document.getElementById('friendsGroupSettings').style.display='';
  // Admin bayroqlari asosida "🛡 Ruxsatlar" tugmasini yashirish/ko'rsatish.
  _applyAppConfig();
  renderGroupMembers();
}

function _sumChips(s){
  // Guruh kontekstida faqat reja + odat ko'rinadi (maqsad olib tashlandi).
  const chips=[];
  if(s.plans_total)chips.push(`<span class="chip ${s.plans_done>=s.plans_total?'ok':''}">📅 ${s.plans_done}/${s.plans_total}</span>`);
  if(s.habits_total)chips.push(`<span class="chip ${s.habits_done_today>=s.habits_total?'ok':''}">🔁 ${s.habits_done_today}/${s.habits_total}</span>`);
  if(!chips.length)chips.push('<span class="chip">bugun bo\'sh</span>');
  return chips.join('');
}

function renderGroupMembers(){
  const el=document.getElementById('friendsMembersList');
  const g=State.currentGroup;
  if(!el||!g)return;
  el.innerHTML=(g.members||[]).map(m=>{
    const initial=(m.name||'?').trim().charAt(0).toUpperCase();
    const role=m.role==='owner'?' <span class="chip mine" style="padding:1px 6px">EGA</span>':'';
    // Yashirin a'zo (menga ochmagan) — summary chip'lari o'rniga qulf.
    const visible = m.is_me || m.visible!==false;
    const chips = visible
      ? `${_sumChips(m.summary||{})} <span class="chip">🔥 ${m.streak||0}</span>`
      : `<span class="chip">🔒 yashirin</span> <span class="chip">🔥 ${m.streak||0}</span>`;
    // Chiqarib yuborish tugmasi kartada YO'Q — u guruh sozlamalari ichida
    // (faqat ega uchun). Bu yerda har doim chevron ko'rinadi.
    return `<div class="mem-card ${m.is_me?'me':''}" data-uid="${m.user_id}">
      <div class="av">${initial}</div>
      <div class="body">
        <div class="nm">${esc(m.name)}${m.is_me?' (siz)':''}${role}</div>
        <div class="st">${chips}</div>
      </div>
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" style="color:var(--text-3)"><polyline points="9 6 15 12 9 18"/></svg>
    </div>`;
  }).join('');
  // A'zoni ochish
  el.querySelectorAll('.mem-card').forEach(c=>c.onclick=()=>openMember(+c.dataset.uid));
}

async function openMember(uid,dateStr){
  const g=State.currentGroup;if(!g)return;
  State.memberUid=uid;
  State.memberDate=dateStr||ymd(new Date());
  let d;try{d=await apiMemberView(g.id,uid,State.memberDate);}catch(e){toast('A\'zo yuklanmadi',true);return;}
  State.currentMember=d;
  // Server sana'ni normallashtirishi mumkin (kelajak → bugun); moslaymiz.
  if(d.date)State.memberDate=d.date;
  _showFriendsView('member');
  document.getElementById('friendsMemberName').textContent=(d.member.name||'—')+(d.member.is_me?' (siz)':'');
  document.getElementById('friendsMemberSub').textContent='🔥 '+(d.member.streak||0)+' kun · ⭐ '+(d.member.total_score||0)+' ball';
  _updateMemberDateNav();
  renderMemberContent();
}

// Sana navigatsiyasi holati (label). Chegara YO'Q — foydalanuvchi istagan
// yo'nalishga (o'tgan/kelajak) o'tishi mumkin. Bugundan uzoq bo'lgan sana
// yorlig'i "Bugun+N kun" / "Bugun-N kun" ko'rinishida ham tuslanmaydi — to'la
// sana ko'rsatiladi (masalan "Chorshanba, 15 iyul"). Bir tez qaytish uchun
// yorliqni bosish "Bugun"ga qaytaradi.
function _updateMemberDateNav(){
  const lbl=document.getElementById('memDateLabel');
  const todayStr=ymd(new Date());
  const yStr=ymd(addDays(new Date(),-1));
  const tStr=ymd(addDays(new Date(),1));
  const cur=State.memberDate||todayStr;
  let text;
  if(cur===todayStr)text='Bugun';
  else if(cur===yStr)text='Kecha';
  else if(cur===tStr)text='Ertaga';
  else{try{text=formatDateLong(new Date(cur+'T00:00:00'));}catch(_){text=cur;}}
  if(lbl){
    lbl.textContent=text;
    lbl.style.cursor='pointer';
    lbl.title='Bugunga qaytish uchun bosing';
    lbl.onclick=()=>{ if(State.memberDate!==todayStr && State.memberUid!=null) openMember(State.memberUid,todayStr); };
  }
}
function _shiftMemberDate(deltaDays){
  const cur=State.memberDate||ymd(new Date());
  const nd=addDays(new Date(cur+'T00:00:00'),deltaDays);
  if(State.memberUid!=null)openMember(State.memberUid,ymd(nd));
}
// Bir oy oldinga yoki keyinga sakrash — maqsadlar boshqa oy/yilga o'tadi.
// Kun raqami saqlanadi (yo'q bo'lsa oyning oxirgi kuniga tushiriladi).
function _shiftMemberMonth(deltaMonths){
  const cur=State.memberDate||ymd(new Date());
  const d=new Date(cur+'T00:00:00');
  const targetY=d.getFullYear(), targetM=d.getMonth()+deltaMonths;
  const nd=new Date(targetY, targetM, 1);
  // Kun raqamini asosiy sanadan olishga urinamiz (yoki oxirgi kun)
  const lastDayOfTarget=new Date(nd.getFullYear(), nd.getMonth()+1, 0).getDate();
  nd.setDate(Math.min(d.getDate(), lastDayOfTarget));
  if(State.memberUid!=null)openMember(State.memberUid,ymd(nd));
}
// Goal davrini o'qish uchun qulay label.
//   yearly "2026"      -> "📅 2026-yil"
//   monthly "2026-07"  -> "🗓 Iyul 2026"
function _formatGoalPeriod(gt, period){
  try{
    const p=String(period||'').trim();
    if(!p)return (gt==='monthly'?'oylik':'yillik');
    if(gt==='yearly'){return '📅 '+p+'-yil';}
    if(gt==='monthly'){
      const [y,m]=p.split('-').map(n=>parseInt(n,10));
      if(!y||!m||m<1||m>12)return '🗓 '+p;
      return '🗓 '+UZ_MONTHS[m-1]+' '+y;
    }
    return p;
  }catch(_){return String(period||'');}
}

function renderMemberContent(){
  const d=State.currentMember;if(!d)return;
  const wrap=document.getElementById('friendsMemberContent');
  const isToday=d.is_today!==false;
  const isFuture=!!d.is_future;
  const isPast=!!d.is_past;
  // Yaratish tugmalari har doim ko'rinadi (agar ruxsat bo'lsa): plan modali
  // sana tanlashni, habit modali muddat, goal modali esa davrni (yillik/oylik +
  // yil + oy) o'zi so'raydi. Ya'ni o'tgan yoki kelajakdagi kun ko'rinishida
  // ham foydalanuvchi istagan davri uchun qo'sha oladi.
  const canManage=d.can_manage&&!d.member.is_me;

  // Yashirin a'zo: reja/odat/maqsad ma'lumotlari ko'rsatilmaydi.
  // Ammo profil (ism, streak, ball) ko'rinadi (leaderboard'da baribir ochiq).
  if(d.visible===false){
    wrap.innerHTML=`
      <div style="margin-top:22px;padding:22px 16px;text-align:center;background:var(--surface);border:1px dashed var(--border);border-radius:16px">
        <div style="font-size:34px;line-height:1;margin-bottom:8px">🔒</div>
        <div style="font-size:14px;font-weight:700;margin-bottom:4px">Ma'lumotlari yashirin</div>
        <div style="font-size:12px;color:var(--text-2);line-height:1.5">Bu a'zo o'zining reja, odat va maqsadlarini sizga ko'rsatmagan.<br>Ko'rish uchun undan Ruxsatlar (👁) da sizga ochishini so'rang.</div>
      </div>
    `;
    return;
  }

  // Guruh kontekstida maqsad (goals) ko'rinmaydi.
  const plans=d.plans||[],habits=d.habits||[];

  // Rejalar — vaqti bo'yicha saralanadi (erta vaqt tepada; vaqtsiz oxirda).
  const _sortedPlans=plans.slice().sort((a,b)=>{
    const ta=a.scheduled_time||'99:99', tb=b.scheduled_time||'99:99';
    return ta.localeCompare(tb);
  });
  const plansHtml=_sortedPlans.length?_sortedPlans.map(p=>{
    const done=p.status==='done';const tag=p.scheduled_time?`<span class="meta">⏰ ${esc(p.scheduled_time)}</span>`:'';
    return `<div class="mem-item ${done?'done':''}"><div class="cbx ${done?'done':''}">${done?'✓':''}</div><div class="ttl">${esc(p.title)}</div>${tag}</div>`;
  }).join(''):'<div style="font-size:12px;color:var(--text-3);padding:6px">Reja yo\'q</div>';

  // Odatlar — eslatma vaqti bo'yicha saralanadi (backend allaqachon saralab
  // qaytaradi, lekin himoya sifatida frontendda ham).
  const _sortedHabits=habits.slice().sort((a,b)=>{
    const ta=a.reminder_time||'99:99', tb=b.reminder_time||'99:99';
    return ta.localeCompare(tb);
  });
  const habitsHtml=_sortedHabits.length?_sortedHabits.map(h=>{
    const done=h.done_today;
    // Meta chapdan o'ngga: ⏰ eslatma vaqti (bo'lsa) · takrorlanish turi.
    const timePart=h.reminder_time?`⏰ ${esc(h.reminder_time)}`:'';
    const freqPart=h.frequency==='weekly'?'haftalik':'har kuni';
    const meta=timePart?`${timePart} · ${freqPart}`:freqPart;
    return `<div class="mem-item ${done?'done':''}"><div class="cbx ${done?'done':''}">${done?'✓':''}</div><div class="ttl">${esc(h.icon||'✅')} ${esc(h.title)}</div><span class="meta">${meta}</span></div>`;
  }).join(''):'<div style="font-size:12px;color:var(--text-3);padding:6px">Odat yo\'q</div>';

  // Yaratish tugmalari — endi faqat reja va odat (maqsad guruh kontekstida
  // olib tashlandi). A'zolar bir-biriga maqsad qo'sha olmaydi.
  const createBtns=canManage?`
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:12px">
      <button class="btn btn-ghost" data-fmnew="plan" style="font-size:12.5px">+ Reja</button>
      <button class="btn btn-ghost" data-fmnew="habit" style="font-size:12.5px">+ Odat</button>
    </div>
    <p style="font-size:11.5px;color:var(--text-3);margin-top:8px;text-align:center">Bu a'zo sizga o'zi uchun reja va odat yaratishga ruxsat bergan.</p>`:'';

  const noPermHint=(!canManage&&!d.member.is_me)?`<p style="font-size:11.5px;color:var(--text-3);margin-top:12px;text-align:center;padding:10px;background:var(--surface);border:1px dashed var(--border);border-radius:12px">🛡 Bu a'zo sizga u uchun reja yaratishga ruxsat bermagan.</p>`:'';

  const plansTitle=isToday?'📅 Bugungi rejalar':(isFuture?'📅 Kelajakdagi rejalar':'📅 Rejalar');
  let banner='';
  if(isPast){
    banner=`<div style="margin:12px 0 2px;padding:8px 12px;background:var(--primary-soft);border-radius:12px;font-size:12px;color:var(--primary);font-weight:600;text-align:center">🕰 O'tgan kun ko'rinishi</div>`;
  }else if(isFuture){
    banner=`<div style="margin:12px 0 2px;padding:8px 12px;background:var(--primary-soft);border-radius:12px;font-size:12px;color:var(--primary);font-weight:600;text-align:center">🔮 Kelajakdagi kun ko'rinishi</div>`;
  }
  const pastBanner=banner;
  wrap.innerHTML=`
    ${pastBanner}
    <div class="section-title" style="margin-top:14px"><h2 style="font-size:14px">${plansTitle} (${plans.filter(p=>p.status==='done').length}/${plans.length})</h2></div>
    ${plansHtml}
    <div class="section-title" style="margin-top:14px"><h2 style="font-size:14px">🔁 Odatlar</h2></div>
    ${habitsHtml}
    ${createBtns}
    ${noPermHint}
  `;
  wrap.querySelectorAll('[data-fmnew]').forEach(b=>b.onclick=()=>openCreateForMember(b.dataset.fmnew));
}

// A'zo uchun yangi resurs yaratishda — o'ziga xos plan/habit/goal modallarini
// qayta ishlatamiz (barcha maydonlar bilan: eslatma vaqti, sana, belgi,
// takrorlash, davomiylik, eslatma va h.k.). `State.forMemberContext` set
// bo'lsa saqlash friends API'ga (a'zoning hisobiga) yo'naltiriladi.
function openCreateForMember(kind){
  const g=State.currentGroup, m=State.currentMember;
  if(!g||!m||m.member.is_me){return;}
  State.forMemberContext={groupId:g.id, userId:m.member.user_id, name:m.member.name};
  if(kind==='plan'){
    openPlanModal(null);
    setText('planModalTitle', m.member.name+' uchun yangi reja');
  }else if(kind==='habit'){
    openHabitModal(null);
    setText('habitModalTitle', m.member.name+' uchun yangi odat');
  }
  // Guruh kontekstida "boshqa a'zo uchun maqsad qo'shish" oqimi olib tashlandi.
}

// ── Guruh yaratish modali ────────────────────────────────
function openGroupCreateModal(){
  document.getElementById('gcName').value='';
  document.getElementById('gcDesc').value='';
  document.getElementById('groupCreateBack').classList.add('show');
  setTimeout(()=>document.getElementById('gcName').focus(),200);
}
async function saveGroupCreate(){
  const name=document.getElementById('gcName').value.trim();
  const desc=document.getElementById('gcDesc').value.trim();
  if(!name){toast('Nom bo\'sh',true);return;}
  try{
    await apiGroupCreate(name,desc||null);
    document.getElementById('groupCreateBack').classList.remove('show');
    toast('✨ Guruh yaratildi');
    await loadGroupsAPI();
  }catch(e){toast('Xato: '+e.message,true);}
}

// ── Guruh sozlamalari (3 tab: Umumiy / Hisobot / A'zolar) ─────
function selectGroupEditTab(name){
  // Aktiv tab tugmasini va shu tabga tegishli panel'ni ko'rsatadi.
  const validTabs = ['general', 'digest', 'members'];
  if(!validTabs.includes(name)) name = 'general';
  document.querySelectorAll('.ge-tab').forEach(btn=>{
    const on = btn.dataset.geTab === name;
    btn.classList.toggle('active', on);
    btn.setAttribute('aria-selected', on ? 'true' : 'false');
  });
  document.querySelectorAll('.ge-pane').forEach(p=>{
    p.classList.toggle('active', p.dataset.gePane === name);
  });
}

function openGroupEditModal(){
  const g=State.currentGroup;if(!g)return;
  document.getElementById('geName').value=g.name||'';
  document.getElementById('geDesc').value=g.description||'';
  document.getElementById('geDelete').style.display=g.is_owner?'':'none';
  document.getElementById('geLeave').style.display=g.is_owner?'none':'';
  document.getElementById('geSave').style.display=g.is_owner?'':'none';
  document.getElementById('geName').disabled=!g.is_owner;
  document.getElementById('geDesc').disabled=!g.is_owner;
  renderGroupEditMembers();
  // Hisobot va A'zolar tab'lari faqat guruh egasi uchun ko'rinadi.
  document.querySelectorAll('.ge-tab').forEach(btn=>{
    const t=btn.dataset.geTab;
    if(t==='digest' || t==='members'){
      btn.style.display = g.is_owner ? '' : 'none';
    }
  });
  // Telegram digest bo'limi faqat ega uchun ko'rinadi.
  const dw=document.getElementById('geDigestWrap');
  if(dw)dw.style.display=g.is_owner?'':'none';
  if(g.is_owner)loadDigestSettings();
  // Har safar birinchi tab ("Umumiy") ochilishi uchun reset.
  selectGroupEditTab('general');
  document.getElementById('groupEditBack').classList.add('show');
}

// ── Telegram digest — sozlamalar holati va UI ──────────────
State.digest={settings:null, candidates:null, loading:false, savingKey:null};

async function loadDigestSettings(){
  const g=State.currentGroup;if(!g||!g.is_owner)return;
  try{
    const s=await apiDigestSettings(g.id);
    State.digest.settings=s;
    renderDigestSettings();
  }catch(e){
    State.digest.settings=null;
    console.warn('digest settings',e);
  }
}

function _fillDigestTimeOptions(sel, current){
  if(!sel)return;
  // Backend `allowed_times` ni ham beradi, ammo default katalog 06:00..23:00.
  const times=(State.digest.settings&&State.digest.settings.allowed_times)||
    Array.from({length:18},(_,i)=>String(i+6).padStart(2,'0')+':00');
  let opts='';
  const cur=current||'21:00';
  const hasCur=times.includes(cur);
  if(!hasCur)opts+='<option value="'+esc(cur)+'" selected>'+esc(cur)+'</option>';
  for(const t of times){
    opts+='<option value="'+esc(t)+'"'+(t===cur?' selected':'')+'>'+esc(t)+'</option>';
  }
  sel.innerHTML=opts;
}

function renderDigestSettings(){
  const s=State.digest.settings;
  const wrap=document.getElementById('geDigestWrap');
  if(!wrap||!s)return;
  // Enable toggle — kunlik HISOBOT
  const enBtn=document.getElementById('geDigestEnable');
  if(enBtn){
    enBtn.classList.toggle('on', !!s.digest_enabled);
    if(!s.telegram_chat_id){
      enBtn.classList.add('disabled');
    }else{
      enBtn.classList.remove('disabled');
    }
  }
  // Chat title
  const chatEl=document.getElementById('geDigestChat');
  if(chatEl){
    if(s.telegram_chat_id){
      chatEl.textContent=s.telegram_chat_title||('Chat #'+s.telegram_chat_id);
    }else{
      chatEl.textContent='— tanlanmagan —';
    }
  }
  // Unlink tugmasi
  const unlinkBtn=document.getElementById('geDigestUnlink');
  if(unlinkBtn)unlinkBtn.style.display=s.telegram_chat_id?'':'none';
  // Vaqt selektorlari — hisobot va rejalar
  _fillDigestTimeOptions(document.getElementById('geDigestTime'), s.digest_time);
  _fillDigestTimeOptions(document.getElementById('gePlansTime'), s.plans_time||'07:00');
  // Ma'lumot manbasi (plans/habits/both) — segmentli tugmalar
  const currentSrc = (s.report_source || 'both').toLowerCase();
  document.querySelectorAll('#geReportSourceSeg .src-opt').forEach(b=>{
    const on = b.dataset.src === currentSrc;
    b.classList.toggle('active', on);
    b.setAttribute('aria-checked', on ? 'true' : 'false');
  });
  // Kunlik REJA (plans) enable toggle
  const plansEnBtn=document.getElementById('gePlansEnable');
  if(plansEnBtn){
    plansEnBtn.classList.toggle('on', !!s.plans_enabled);
    if(!s.telegram_chat_id){
      plansEnBtn.classList.add('disabled');
    }else{
      plansEnBtn.classList.remove('disabled');
    }
  }
  // Meta — foydalanuvchi so'ragan: oxirgi muvaffaqiyatli yuborish vaqti
  // KERAK EMAS. Faqat xato bo'lgan hollarda ogohlantirish ko'rinadi.
  const meta=document.getElementById('geDigestMeta');
  if(meta){
    const parts=[];
    if(s.digest_last_error){
      parts.push('⚠️ Hisobot xato: '+s.digest_last_error);
    }
    if(s.plans_last_error){
      parts.push('⚠️ Reja xato: '+s.plans_last_error);
    }
    meta.innerHTML=parts.map(esc).join(' · ');
  }
}

async function _digestSet(patch, key){
  const g=State.currentGroup;if(!g||!g.is_owner)return;
  if(State.digest.savingKey)return; // ikki marta bosilishdan himoya
  State.digest.savingKey=key||'save';
  try{
    const s=await apiDigestUpdate(g.id, patch);
    State.digest.settings=s;
    renderDigestSettings();
  }catch(e){
    const m=String(e&&e.message||'');
    // Backend detail'ini o'qishga urinamiz
    toast('Xato: '+m,true);
    // Kelib chiqqan xato holatini qayta yuklaymiz (UI hozirgi haqiqiy holatga qaytadi)
    loadDigestSettings();
  }finally{
    State.digest.savingKey=null;
  }
}

async function toggleDigestEnable(){
  const s=State.digest.settings;if(!s)return;
  if(!s.telegram_chat_id){
    toast('Avval Telegram guruhni tanlang',true);
    return;
  }
  await _digestSet({digest_enabled: !s.digest_enabled}, 'enable');
  const nowOn=State.digest.settings && State.digest.settings.digest_enabled;
  toast(nowOn?'✅ Kunlik hisobot yoqildi':'⏸ Kunlik hisobot to\'xtatildi');
}
async function togglePlansEnable(){
  const s=State.digest.settings;if(!s)return;
  if(!s.telegram_chat_id){
    toast('Avval Telegram guruhni tanlang',true);
    return;
  }
  await _digestSet({plans_enabled: !s.plans_enabled}, 'plansenable');
  const nowOn=State.digest.settings && State.digest.settings.plans_enabled;
  toast(nowOn?'✅ Kunlik reja yuborish yoqildi':'⏸ Kunlik reja yuborish to\'xtatildi');
}
async function changeDigestTime(){
  const s=State.digest.settings;if(!s)return;
  const sel=document.getElementById('geDigestTime');
  if(!sel)return;
  const nv=sel.value;
  if(nv===s.digest_time)return;
  await _digestSet({digest_time: nv}, 'time');
  toast('📊 Hisobot vaqti: '+nv);
}
async function changePlansTime(){
  const s=State.digest.settings;if(!s)return;
  const sel=document.getElementById('gePlansTime');
  if(!sel)return;
  const nv=sel.value;
  if(nv===(s.plans_time||'07:00'))return;
  await _digestSet({plans_time: nv}, 'planstime');
  toast('📋 Reja vaqti: '+nv);
}

// Ma'lumot manbasi tanlovi (plans/both/habits) — segmentli tugmalardan biri.
// Optimistic UI: darhol active klass o'zgaradi; xato bo'lsa qaytariladi.
async function selectReportSource(nextSrc){
  const s=State.digest.settings;if(!s)return;
  const valid = ['plans','both','habits'];
  if(!valid.includes(nextSrc)) return;
  const prev = (s.report_source || 'both').toLowerCase();
  if(nextSrc===prev) return;
  // Optimistic UI
  const seg=document.getElementById('geReportSourceSeg');
  if(seg){
    seg.querySelectorAll('.src-opt').forEach(b=>{
      const on = b.dataset.src === nextSrc;
      b.classList.toggle('active', on);
      b.classList.add('busy');
      b.setAttribute('aria-checked', on ? 'true' : 'false');
    });
  }
  try{
    await _digestSet({report_source: nextSrc}, 'source');
    const label = nextSrc==='plans' ? '📋 Faqat rejalar'
                : nextSrc==='habits' ? '🔁 Faqat odatlar'
                : '🔀 Ikkisi ham';
    toast('Ma\'lumot manbasi: '+label);
  }catch(_){
    // _digestSet o'zi loadDigestSettings chaqiradi xato bo'lsa
  }finally{
    if(seg) seg.querySelectorAll('.src-opt').forEach(b=>b.classList.remove('busy'));
  }
}

async function unlinkDigestChat(){
  const g=State.currentGroup;if(!g||!g.is_owner)return;
  if(!await confirmDialog({title:'Bog\'lanishni uzish',message:'Telegram guruhga hisobot yuborish to\'xtatiladi. Bog\'lash saqlanmaydi. Davom etamizmi?'}))return;
  try{
    await apiDigestUnlink(g.id);
    toast('🔌 Bog\'lanish uzildi');
    await loadDigestSettings();
  }catch(e){toast('Xato: '+e.message,true);}
}

// ── Yangi: ikkita alohida test yuborish funksiyasi (kunlik reja / kunlik hisobot)
// Xabar tarkibida "test" yozuvi bo'lmaydi — real avtomatik yuborish bilan
// aynan bir xil ko'rinishda. Faqat DB'dagi last_sent_at yangilanmaydi.
async function _runTestSend(kind /* 'plans' | 'report' */){
  const g=State.currentGroup;if(!g||!g.is_owner)return;
  const s=State.digest.settings;
  if(!s||!s.telegram_chat_id){toast('Avval Telegram guruhni tanlang',true);return;}
  const btnId = kind==='plans' ? 'gePlansTest' : 'geDigestTest';
  const btn=document.getElementById(btnId);
  // Tugma icon-only bo'lgani uchun matnni almashtirmaymiz — faqat opacity va
  // disabled bilan yuklanish holatini ko'rsatamiz.
  if(btn){btn.disabled=true;btn.style.opacity='.55';}
  try{
    const r = kind==='plans'
      ? await apiPlansTest(g.id)
      : await apiReportTest(g.id);
    if(r&&r.ok){
      toast(kind==='plans' ? '📨 Kunlik reja yuborildi' : '📨 Kunlik hisobot yuborildi');
    }else{
      toast('⚠️ '+(r&&r.reason||'Yuborib bo\'lmadi'),true);
    }
  }catch(e){
    toast('Xato: '+e.message,true);
  }finally{
    if(btn){btn.disabled=false;btn.style.opacity='';}
    // Xato bo'lgan bo'lsa auto-unlink bo'lishi mumkin — qayta yuklab olamiz.
    loadDigestSettings();
  }
}
async function sendPlansTest(){ await _runTestSend('plans'); }
async function sendDigestTest(){ await _runTestSend('report'); }

// ── Chat picker: bot bilan birga bo'lgan Telegram guruhlar ro'yxati ─────
async function openDigestPicker(){
  const g=State.currentGroup;if(!g||!g.is_owner)return;
  const back=document.getElementById('tgPickerBack');
  const list=document.getElementById('tgPickerList');
  if(!back||!list)return;
  list.innerHTML='<div class="tgp-empty">⏳ Yuklanmoqda…</div>';
  back.classList.add('show');
  try{
    const r=await apiDigestCandidates(g.id);
    State.digest.candidates=r&&r.candidates||[];
    renderDigestCandidates();
  }catch(e){
    list.innerHTML='<div class="tgp-empty">Xato: '+esc(e.message||'')+'</div>';
  }
}

function renderDigestCandidates(){
  const list=document.getElementById('tgPickerList');
  const arr=State.digest.candidates||[];
  if(!list)return;
  if(!arr.length){
    list.innerHTML=`<div class="tgp-empty">
      Ro'yxat bo'sh.<br><br>
      Botni Telegram guruhingizga qo'shing va o'sha guruhda kamida bir marta xabar yozing.
      Undan keyin ro'yxatda paydo bo'ladi.
    </div>`;
    return;
  }
  list.innerHTML=arr.map(c=>{
    const initial=(c.chat_title||'?').trim().charAt(0).toUpperCase();
    const warn=c.can_send?'':'<div class="tgp-warn">⚠️ Bot xabar yubora olmaydi. Guruhda "faqat adminlar yozadi" yoqilgan bo\'lsa, botni admin qiling.</div>';
    return `<div class="tgp-item ${c.is_selected?'selected':''}" data-cid="${c.chat_id}" data-title="${esc(c.chat_title||'')}">
      <div class="tgp-icon">${esc(initial)}</div>
      <div class="tgp-body">
        <div class="tgp-title">${esc(c.chat_title||('Chat #'+c.chat_id))}</div>
        <div class="tgp-meta">${esc(c.chat_type||'group')} · id ${c.chat_id}${c.is_selected?' · tanlangan':''}</div>
        ${warn}
      </div>
    </div>`;
  }).join('');
  list.querySelectorAll('.tgp-item').forEach(el=>{
    el.onclick=async()=>{
      const g=State.currentGroup;if(!g)return;
      const cid=parseInt(el.dataset.cid,10);
      const title=el.dataset.title||null;
      try{
        await apiDigestLink(g.id, cid, title);
        document.getElementById('tgPickerBack').classList.remove('show');
        toast('🔗 Guruh bog\'landi. Yoqing va vaqtni tanlang.');
        await loadDigestSettings();
      }catch(e){
        toast('Xato: '+e.message,true);
      }
    };
  });
}


// Guruh sozlamalari ichidagi a'zolarni boshqarish — FAQAT ega ko'radi.
// Har bir non-owner a'zo yonida "Chiqarish" tugmasi (kartada emas, shu yerda).
function renderGroupEditMembers(){
  const g=State.currentGroup;
  const box=document.getElementById('geMembers');
  const wrap=document.getElementById('geMembersWrap');
  if(!box||!wrap)return;
  if(!g||!g.is_owner){wrap.style.display='none';box.innerHTML='';return;}
  wrap.style.display='';
  // A'zolar ro'yxati — barcha a'zolar, jumladan guruh egasi (o'zi) ham.
  // Foydalanuvchi so'ragan: ega o'zining ma'lumotlarini yashira olishi kerak.
  // Ega uchun chiqarish (🗑) tugmasi ko'rsatilmaydi — u o'zini chiqara olmaydi.
  // Tartib: ega tepada, keyin qolganlar.
  const list = (g.members||[]).slice().sort((a,b)=>{
    if(a.is_me && !b.is_me) return -1;
    if(!a.is_me && b.is_me) return 1;
    return 0;
  });
  box.innerHTML=list.map(m=>{
    const active = m.is_active !== false;  // default TRUE (backward compat)
    const isMe = !!m.is_me;
    const nameTag = isMe ? ' <span class="ge-mem-tag">EGA</span>' : '';
    const kickBtn = isMe ? '' : `<button class="btn-icon btn-icon-danger" data-kick="${m.user_id}" data-name="${esc(m.name)}" title="Guruhdan chiqarish" aria-label="Guruhdan chiqarish">🗑</button>`;
    return `
    <div class="perm-row ge-mem-row${active?'':' ge-mem-off'}${isMe?' ge-mem-me':''}">
      <div class="nm">${esc(m.name)}${nameTag}</div>
      <div class="ge-mem-actions">
        <div class="toggle ${active?'on':''}" data-active-uid="${m.user_id}" role="switch" aria-label="${active?'O\'chirish':'Yoqish'}" title="${active?'Aktiv — ma\'lumotlari ko\'rinadi':'O\'chirilgan — ma\'lumotlari yashirin'}"><i></i></div>
        ${kickBtn}
      </div>
    </div>`;
  }).join('');

  // ── Aktiv toggle click handler
  box.querySelectorAll('[data-active-uid]').forEach(t=>t.onclick=async()=>{
    if(t.classList.contains('busy'))return;  // ikki marta bosishdan himoya
    const uid=+t.dataset.activeUid;
    const nextActive = !t.classList.contains('on');
    t.classList.add('busy');
    // Optimistic UI: darhol o'zgartiramiz; xato bo'lsa qaytaramiz.
    t.classList.toggle('on', nextActive);
    const row=t.closest('.perm-row');
    if(row)row.classList.toggle('ge-mem-off', !nextActive);
    try{
      await apiSetMemberActive(g.id, uid, nextActive);
      toast(nextActive ? '✅ A\'zo yoqildi' : '⏸ A\'zo o\'chirildi (ma\'lumotlari yashirin)');
      // State.currentGroup.members ichidagi is_active flag'ni yangilaymiz —
      // modal qayta ochilganda toggle to'g'ri holatda ko'rinsin (openGroup
      // chaqiruvi UI'ni orqada refresh qilmaydi).
      const gm = (State.currentGroup && State.currentGroup.members || []).find(x=>x.user_id===uid);
      if(gm) gm.is_active = nextActive;
    }catch(err){
      // Rollback UI
      t.classList.toggle('on', !nextActive);
      if(row)row.classList.toggle('ge-mem-off', nextActive);
      const msg=String(err&&err.message||'');
      if(msg.includes('403'))toast('🛡 Faqat guruh egasi',true);
      else toast('Xato: '+msg,true);
    }finally{
      t.classList.remove('busy');
    }
  });

  // ── Chiqarish (kick) tugma click handler
  box.querySelectorAll('[data-kick]').forEach(b=>b.onclick=async()=>{
    const uid=+b.dataset.kick;
    const name=b.dataset.name||'a\'zo';
    if(!await confirmDialog({title:'Chiqarib yuborish', message:`«${name}» guruhdan chiqarilsinmi? Uning ushbu guruhga tegishli ruxsatlari ham tozalanadi.`}))return;
    try{
      await apiRemoveMember(g.id, uid);
      toast('👋 A\'zo chiqarildi');
      await openGroup(g.id);          // guruh detali yangilanadi
      renderGroupEditMembers();       // modal ro'yxati ham yangilanadi
    }catch(err){
      const msg=String(err&&err.message||'');
      if(msg.includes('403'))toast('🛡 Faqat guruh egasi',true);
      else toast('Xato: '+msg,true);
    }
  });
}
async function saveGroupEdit(){
  const g=State.currentGroup;if(!g||!g.is_owner)return;
  const name=document.getElementById('geName').value.trim();
  const desc=document.getElementById('geDesc').value.trim();
  if(!name){toast('Nom bo\'sh',true);return;}
  try{
    await apiGroupPatch(g.id,{name,description:desc||null});
    document.getElementById('groupEditBack').classList.remove('show');
    toast('✓ Yangilandi');
    await loadGroupsAPI();
    await openGroup(g.id);
  }catch(e){toast('Xato: '+e.message,true);}
}
async function deleteCurrentGroup(){
  const g=State.currentGroup;if(!g||!g.is_owner)return;
  if(!await confirmDialog({title:'Guruhni o\'chirish',message:'Barcha a\'zolar va ruxsatlar yo\'q qilinadi. Davom etamizmi?'}))return;
  try{await apiGroupDelete(g.id);toast('🗑 O\'chirildi');document.getElementById('groupEditBack').classList.remove('show');State.currentGroup=null;await loadGroupsAPI();}
  catch(e){toast('Xato: '+e.message,true);}
}
async function leaveCurrentGroup(){
  const g=State.currentGroup;if(!g)return;
  if(!await confirmDialog({title:'Guruhdan chiqish',message:'Bu guruhni tark etasizmi?'}))return;
  try{await apiGroupLeave(g.id);toast('👋 Chiqdingiz');document.getElementById('groupEditBack').classList.remove('show');State.currentGroup=null;await loadGroupsAPI();}
  catch(e){toast('Xato: '+e.message,true);}
}

// ── Do'st taklif qilish (Telegram share) ─────────────────
async function _resolveBotUsername(){
  if(State.botUsername)return State.botUsername;
  // Profil endpointidagi referral_link ichida bot username bor
  // (masalan https://t.me/intizomAi_bot?start=ref_123).
  try{
    const p=await api('/api/webapp/profile');
    const m=/t\.me\/([^\/\?]+)/i.exec(p&&p.referral_link||'');
    if(m&&m[1])State.botUsername=m[1];
  }catch(_){}
  return State.botUsername||'intizomAi_bot';
}
async function inviteFriend(){
  const g=State.currentGroup;if(!g)return;
  const bot=await _resolveBotUsername();
  const link='https://t.me/'+encodeURIComponent(bot)+'?start=grp_'+encodeURIComponent(g.invite_code);
  const text='👥 «'+g.name+'» guruhiga taklif etilyapsiz! Intizom AI botiga qo\'shiling va birga intizomli bo\'ling.';
  const shareUrl='https://t.me/share/url?url='+encodeURIComponent(link)+'&text='+encodeURIComponent(text);
  // Telegram Mini App'da native share sheet ochiladi (kontakt tanlash).
  try{if(tg&&tg.openTelegramLink){tg.openTelegramLink(shareUrl);return;}}catch(_){}
  window.open(shareUrl,'_blank');
}

// ── Ruxsatlar modali — Boshqarish (can_manage) + info panel ──────────────
// "Kim meni ko'radi" (can_view) toggle olib tashlangan — hamma bir-birining
// reja/odatlarini har doim ko'radi. Visibility endi faqat guruh egasi
// A'zolar bo'limidagi on/off toggle bilan boshqariladi.
async function openPermsModal(){
  const g=State.currentGroup;if(!g)return;
  let d;try{d=await apiPerms(g.id);}catch(e){toast('Ruxsatlar yuklanmadi',true);return;}

  const manageEl=document.getElementById('permsGrantsOut');
  const inEl=document.getElementById('permsGrantsIn');
  const members=d.grants_out||[];
  const empty='<div style="font-size:12px;color:var(--text-3);padding:6px">Guruhda boshqa a\'zo yo\'q</div>';

  // ✍️ Boshqarish toggle — kim men uchun yarata oladi
  if(!members.length){
    manageEl.innerHTML=empty;
  }else{
    manageEl.innerHTML=members.map(m=>`
      <div class="perm-row">
        <div class="nm">${esc(m.name)}</div>
        <div class="toggle ${m.can_manage?'on':''}" data-manage-uid="${m.user_id}"><i></i></div>
      </div>`).join('');
  }

  // 📥 Menga berilganlar (info) — faqat can_manage huquqi berganlar.
  // `can_view` endi UI'da ma'nosiz (visibility har doim ochiq), shu sabab
  // e'tibordan chetlashtiriladi.
  const givenTo=(d.grants_in||[]).filter(m=>m.can_manage);
  inEl.innerHTML=givenTo.length?givenTo.map(m=>{
    const chip='<span class="chip mine" style="padding:2px 8px;font-size:10.5px;font-weight:800;color:#fff;background:var(--grad);border-radius:999px">✍️ yarata oladi</span>';
    return `<div class="perm-row"><div class="nm">${esc(m.name)}</div>${chip}</div>`;
  }).join(''):'<div style="font-size:12px;color:var(--text-3);padding:6px">Hech kim sizga ruxsat bermagan</div>';

  // ✍️ Boshqarish toggle handler
  manageEl.querySelectorAll('.toggle').forEach(t=>t.onclick=async()=>{
    const uid=+t.dataset.manageUid;
    const nv=!t.classList.contains('on');
    t.classList.toggle('on',nv);
    try{
      await apiPermsSet(g.id,uid,{can_manage:nv});
      toast(nv?'✍️ Yaratish huquqi berildi':'Yaratish huquqi olindi');
    }catch(e){
      t.classList.toggle('on',!nv);
      toast('Xato: '+e.message,true);
    }
  });

  document.getElementById('permsBack').classList.add('show');
}

// A'zo uchun eski soddalashgan modal (fmTitle/fmDesc/fmTime/fmGoalType) olib
// tashlandi — o'rniga o'z-o'zi uchun ishlatiladigan boy modallar
// (plan/habit/goal) qayta ishlatiladi. `openCreateForMember` va save
// handlerlar `State.forMemberContext` orqali friends API'ga yo'naltiradi.

function switchPage(n){
  document.querySelectorAll('.page').forEach(p=>p.classList.toggle('active',p.dataset.page===n));
  // Statistika endi pastki nav'da yo'q — u tepadagi header tugmasi orqali ochiladi.
  // Shuning uchun 'stats' navi bo'sh; 'friends' aksincha 'friends' nav'iga mos.
  document.querySelectorAll('.nav-item, .nav-ai').forEach(x=>x.classList.toggle('active',x.dataset.nav===n));
  if(n==='stats'){renderStats();loadStatsHabits();applyStatsView();}
  if(n==='goals'){renderGoalsView();requestAnimationFrame(moveGoalSegInd);}
  if(n==='habits')loadHabitsAPI();
  if(n==='ai'){loadCheckin();chatGreet();loadPlansRange().then(()=>renderInsights());}
  if(n==='home'){loadSnapshot();loadQuest();renderDayStrip();updateHomePlansTitle();loadHomeHabits();}
  if(n==='profile'){renderAchs();loadProfileMeta();}
  if(n==='friends'){_showFriendsView('list');loadGroupsAPI();}
  updateFabVisibility();
  if(navigator.vibrate)navigator.vibrate(10);
}

function ripple(e){const t=e.currentTarget;const r=t.getBoundingClientRect();const ink=document.createElement('span');ink.className='ripple-ink';const sz=Math.max(r.width,r.height);ink.style.width=ink.style.height=sz+'px';ink.style.left=(e.clientX-r.left-sz/2)+'px';ink.style.top=(e.clientY-r.top-sz/2)+'px';t.appendChild(ink);setTimeout(()=>ink.remove(),600);}

document.addEventListener('DOMContentLoaded',()=>{
  document.documentElement.setAttribute('data-theme',State.theme);applyMode();initUser();renderThemes();
  // Admin panelidan boshqariladigan global bayroqlarni fon rejimida yuklab
  // olamiz (Do'stlar sahifasidagi Ruxsatlar tugmasini shu asosda yashiramiz).
  loadAppConfig();
  // ── Bottom nav: Do'stlar va AI navlari Premium talab qiladi ──
  // Bepul foydalanuvchi tugma bosgach — sahifaga o'tkazMAYMIZ, inline dialog
  // ochamiz ("Premium olish" yoki "Orqaga"). Boshqa navlarga (Asosiy/Maqsad/Odat)
  // hech qanday cheklov yo'q (bepul user ular ichidagi ma'lumotni ko'ra oladi;
  // faqat mutation'lar cheklangan).
  document.querySelectorAll('.nav-item, .nav-ai').forEach(n=>n.onclick=()=>{
    const target=n.dataset.nav;
    if(target==='friends'&&premiumGate({
      icon:'👥',
      title:'Do\'stlar bo\'limi 👥',
      message:'Do\'stlar bo\'limi faqatgina Premium foydalanuvchilar uchun.',
    }))return;
    if(target==='ai'&&premiumGate({
      icon:'✨',
      title:'AI Coach ✨',
      message:'AI sizning barcha maqsad, reja va odatlaringizni ko\'rib turadi.\n\nUshbu bo\'lim faqatgina Premium foydalanuvchilar uchun.',
    }))return;
    switchPage(target);
  });
  // ── Reja qo'shish (Home) — bepul: bot orqali 5/kun, Mini App'da Premium kerak ──
  const _ap=document.getElementById('addPlanBtn');
  if(_ap)_ap.onclick=e=>{
    ripple(e);
    if(premiumGate({
      icon:'➕',
      title:'Reja qo\'shish',
      message:'Mini App orqali reja qo\'shish faqatgina Premium foydalanuvchilar uchun.\n\nBot orqali kuniga 5 tagacha bepul reja qo\'shishingiz mumkin.',
    }))return;
    openPlanModal(null);
  };
  // ── Maqsad qo'shish (Goals) — Premium talab qiladi ──
  document.querySelectorAll('.add-goal-trigger').forEach(b=>{
    b.onclick=e=>{
      ripple(e);
      if(premiumGate({
        icon:'🎯',
        title:'Maqsad qo\'shish 🎯',
        message:'Maqsad qo\'shish faqatgina Premium foydalanuvchilar uchun.',
      }))return;
      // Faqat yillik/oylik. Eski `weekly`/`daily` data-gp qiymatlari kelsa yillikga tushamiz.
      let gp=b.dataset.gp||State.goalPeriod;
      if(gp!=='yearly'&&gp!=='monthly')gp='yearly';
      const pk=(gp==='yearly')?String(State.selectedYear):(State.selectedYear+'-'+pad(State.selectedMonth+1));
      openModal(gp,pk);
    };
  });
  document.getElementById('modeBtn').onclick=()=>{State.mode=State.mode==='dark'?'light':'dark';localStorage.setItem('iz_mode',State.mode);applyMode();toast(State.mode==='dark'?'🌙 Tungi rejim':'☀️ Kunduzgi rejim');};
  // Settings (sozlamalar) tugmasi va profil rasmi -> Profil sahifasi
  const _setBtn=document.getElementById('settingsBtn');if(_setBtn)_setBtn.onclick=()=>switchPage('profile');
  const _hdrAv=document.getElementById('hdrAv');if(_hdrAv)_hdrAv.onclick=()=>switchPage('profile');
  // Statistika endi header'dagi tugma orqali ochiladi (pastki nav'dan olib tashlandi).
  // Statistika (header) — Premium talab qiladi. Bepul user bosgach dialog ochiladi.
  const _stBtn=document.getElementById('statsBtn');
  if(_stBtn)_stBtn.onclick=()=>{
    if(premiumGate({
      icon:'📊',
      title:'Statistika 📊',
      message:'Statistika bo\'limi faqatgina Premium foydalanuvchilar uchun.',
    }))return;
    switchPage('stats');
  };

  // ── Do'stlar (Friends) wiring ──────────────────────────────
  const _fCreate=document.getElementById('friendsCreateBtn');if(_fCreate)_fCreate.onclick=openGroupCreateModal;
  const _fBack1=document.getElementById('friendsGroupBack');if(_fBack1)_fBack1.onclick=()=>_showFriendsView('list');
  const _fBack2=document.getElementById('friendsMemberBack');if(_fBack2)_fBack2.onclick=()=>_showFriendsView('group');
  const _mDP=document.getElementById('memDatePrev');if(_mDP)_mDP.onclick=()=>_shiftMemberDate(-1);
  const _mDN=document.getElementById('memDateNext');if(_mDN)_mDN.onclick=()=>_shiftMemberDate(1);
  const _mMP=document.getElementById('memMonthPrev');if(_mMP)_mMP.onclick=()=>_shiftMemberMonth(-1);
  const _mMN=document.getElementById('memMonthNext');if(_mMN)_mMN.onclick=()=>_shiftMemberMonth(1);
  const _fInv=document.getElementById('friendsInviteBtn');if(_fInv)_fInv.onclick=inviteFriend;
  const _fPerms=document.getElementById('friendsPermsBtn');if(_fPerms)_fPerms.onclick=openPermsModal;
  const _fSet=document.getElementById('friendsGroupSettings');if(_fSet)_fSet.onclick=openGroupEditModal;
  const _gcC=document.getElementById('gcCancel');if(_gcC)_gcC.onclick=()=>document.getElementById('groupCreateBack').classList.remove('show');
  const _gcS=document.getElementById('gcSave');if(_gcS)_gcS.onclick=saveGroupCreate;
  const _gcB=document.getElementById('groupCreateBack');if(_gcB)_gcB.onclick=e=>{if(e.target.id==='groupCreateBack')_gcB.classList.remove('show');};
  const _geC=document.getElementById('geCancel');if(_geC)_geC.onclick=()=>document.getElementById('groupEditBack').classList.remove('show');
  const _geS=document.getElementById('geSave');if(_geS)_geS.onclick=saveGroupEdit;
  const _geD=document.getElementById('geDelete');if(_geD)_geD.onclick=deleteCurrentGroup;
  const _geL=document.getElementById('geLeave');if(_geL)_geL.onclick=leaveCurrentGroup;
  const _geB=document.getElementById('groupEditBack');if(_geB)_geB.onclick=e=>{if(e.target.id==='groupEditBack')_geB.classList.remove('show');};
  const _pC=document.getElementById('permsClose');if(_pC)_pC.onclick=()=>document.getElementById('permsBack').classList.remove('show');
  const _pB=document.getElementById('permsBack');if(_pB)_pB.onclick=e=>{if(e.target.id==='permsBack')_pB.classList.remove('show');};
  // ── Group settings tab navigator ─────────────────────────────
  document.querySelectorAll('.ge-tab').forEach(btn=>{
    btn.onclick=()=>selectGroupEditTab(btn.dataset.geTab);
  });

  // ── Telegram digest/plans wiring ─────────────────────────────
  const _dgEn=document.getElementById('geDigestEnable');if(_dgEn)_dgEn.onclick=toggleDigestEnable;
  const _dgT=document.getElementById('geDigestTime');if(_dgT)_dgT.onchange=changeDigestTime;
  const _dgP=document.getElementById('geDigestPick');if(_dgP)_dgP.onclick=openDigestPicker;
  const _dgU=document.getElementById('geDigestUnlink');if(_dgU)_dgU.onclick=unlinkDigestChat;
  const _dgTest=document.getElementById('geDigestTest');if(_dgTest)_dgTest.onclick=sendDigestTest;
  // Yangi: kunlik REJA (plans) sozlamalari
  const _plEn=document.getElementById('gePlansEnable');if(_plEn)_plEn.onclick=togglePlansEnable;
  const _plT=document.getElementById('gePlansTime');if(_plT)_plT.onchange=changePlansTime;
  const _plTest=document.getElementById('gePlansTest');if(_plTest)_plTest.onclick=sendPlansTest;
  // Ma'lumot manbasi segmentli tugmalar (plans/both/habits)
  document.querySelectorAll('#geReportSourceSeg .src-opt').forEach(b=>{
    b.onclick=()=>selectReportSource(b.dataset.src);
  });
  const _tpC=document.getElementById('tgPickerCancel');if(_tpC)_tpC.onclick=()=>document.getElementById('tgPickerBack').classList.remove('show');
  const _tpR=document.getElementById('tgPickerReload');if(_tpR)_tpR.onclick=openDigestPicker;
  const _tpB=document.getElementById('tgPickerBack');if(_tpB)_tpB.onclick=e=>{if(e.target.id==='tgPickerBack')_tpB.classList.remove('show');};
  // Eski forMemberBack handlerlari olib tashlandi.
  // Odat (habit) wiring
  // Odat qo'shish (Habits) — Premium talab qiladi.
  const _ah=document.getElementById('addHabitBtn');
  if(_ah)_ah.onclick=e=>{
    ripple(e);
    if(premiumGate({
      icon:'✅',
      title:'Odat qo\'shish ✅',
      message:'Odat qo\'shish faqatgina Premium foydalanuvchilar uchun.',
    }))return;
    openHabitModal(null);
  };
  const _hc=document.getElementById('hCancel');if(_hc)_hc.onclick=closeHabitModal;
  const _hs=document.getElementById('hSave');if(_hs)_hs.onclick=saveHabitModal;
  const _hmb=document.getElementById('habitModalBack');if(_hmb)_hmb.onclick=e=>{if(e.target.id==='habitModalBack')closeHabitModal();};
  document.querySelectorAll('#hFreqSeg .hseg-item').forEach(it=>it.onclick=()=>{State.habitFreq=it.dataset.f;if(State.habitFreq==='weekly'&&!State.habitWeekdays.length){const wd=(new Date().getDay()+6)%7;State.habitWeekdays=[wd];renderHabitWeekdays();}applyHabitFreqUI();});
  document.querySelectorAll('#hDurSeg .hseg-item').forEach(it=>it.onclick=()=>{State.habitDur=it.dataset.d;applyHabitDurUI();});
  document.querySelectorAll('#hRemSeg .hseg-item').forEach(it=>it.onclick=()=>{State.habitRem=it.dataset.r;applyHabitRemUI();});
  document.querySelectorAll('#habitViewSeg .hvs').forEach(it=>it.onclick=()=>{State.habitView=it.dataset.hv;renderHabitsPage();});
  const _tp=document.getElementById('trkPrev');if(_tp)_tp.onclick=()=>{State.trackerWeekStart=addDays(State.trackerWeekStart||startOfWeek(new Date()),-7);renderTracker();};
  const _tn=document.getElementById('trkNext');if(_tn)_tn.onclick=()=>{const ns=addDays(State.trackerWeekStart||startOfWeek(new Date()),7);if(ymd(ns)<=ymd(startOfWeek(new Date()))){State.trackerWeekStart=ns;renderTracker();}};
  document.querySelectorAll('#statsSeg .hvs').forEach(it=>it.onclick=()=>{State.statsView=it.dataset.sv;applyStatsView();});
  document.querySelectorAll('#lbSeg .hvs').forEach(it=>it.onclick=()=>{State.lbPeriod=it.dataset.lb;loadLeaderboard();});
  // Ism tahrirlash wiring
  const _ens=document.getElementById('editNameSetting');if(_ens)_ens.onclick=openNameModal;
  const _nc=document.getElementById('nCancel');if(_nc)_nc.onclick=closeNameModal;
  const _ns=document.getElementById('nSave');if(_ns)_ns.onclick=saveNameModal;
  const _nmb=document.getElementById('nameModalBack');if(_nmb)_nmb.onclick=e=>{if(e.target.id==='nameModalBack')closeNameModal();};
  document.querySelectorAll('#goalSeg .seg-item').forEach(s=>s.onclick=()=>{document.querySelectorAll('#goalSeg .seg-item').forEach(x=>x.classList.remove('active'));s.classList.add('active');State.goalPeriod=s.dataset.gp;moveGoalSegInd();renderGoalsView();});
  // dvToggle / diaryPrev / diaryNext / calPrev / calNext / weekPrev / weekNext
  // / dayModalBack handlerlari olib tashlandi — kunlik/haftalik maqsad turlari yo'q.
  document.getElementById('mCancel').onclick=closeModal;document.getElementById('mSave').onclick=saveModal;
  document.getElementById('modalBack').onclick=e=>{if(e.target.id==='modalBack')closeModal();};
  document.getElementById('pCancel').onclick=closePlanModal;document.getElementById('pSave').onclick=savePlanModal;
  document.getElementById('planModalBack').onclick=e=>{if(e.target.id==='planModalBack')closePlanModal();};
  document.getElementById('darkToggle').onclick=()=>{State.mode=State.mode==='dark'?'light':'dark';localStorage.setItem('iz_mode',State.mode);applyMode();toast(State.mode==='dark'?'🌙 Tungi rejim':'☀️ Kunduzgi rejim');};
  // notifToggle va animToggle olib tashlandi — bildirishnomalar va animatsiyalar
  // doimo hamma foydalanuvchi uchun yoniq turadi (Settings sozlamasi yo'q).
  updateFabVisibility();
  // Optimistik: oldingi seansda premium bo'lsa, paywallni darhol yopamiz
  // (teskari "flash" bo'lmasligi uchun). loadSubscription keyin tasdiqlaydi.
  try{if(localStorage.getItem('iz_premium')==='1')closePaywall();}catch(_){}
  loadSubscription();
  loadProfileMeta();
  try{if(State.photoUrl)apiProfileUpdate(null,null,State.photoUrl).catch(()=>{});}catch(_){}
  // Boshlang'ich yuklamalar — bog'liq bo'lmagan so'rovlarni PARALLEL yuboramiz
  // (avval loadPlansAPI().then(...) waterfall edi). Har biri o'z bo'limini
  // mustaqil render qiladi.
  loadPlansAPI();
  loadGoalsAPI();
  loadSnapshot();
  loadQuest();

  // ── AI page wiring ─────────────────────────────────────────────────
  // AI chat wiring (ephemeral suhbat)
  const _chatInput=document.getElementById('chatInput');
  const _chatSend=document.getElementById('chatSend');
  if(_chatInput){_chatInput.addEventListener('input',()=>{_chatInput.style.height='auto';_chatInput.style.height=Math.min(200,_chatInput.scrollHeight)+'px';});}
  if(_chatSend)_chatSend.onclick=()=>chatSend(document.getElementById('chatInput').value);
  document.querySelectorAll('#chatSugg .s').forEach(s=>s.onclick=()=>chatSend(s.dataset.q));
  document.querySelectorAll('#moodRow .mood-pill').forEach(p=>p.onclick=()=>{document.querySelectorAll('#moodRow .mood-pill').forEach(x=>x.classList.remove('active'));p.classList.add('active');State.checkinMood=p.dataset.mood;saveCheckin({mood:State.checkinMood});});
  document.querySelectorAll('#energyRow .energy-cell').forEach(c=>c.onclick=()=>{document.querySelectorAll('#energyRow .energy-cell').forEach(x=>x.classList.remove('active'));c.classList.add('active');State.checkinEnergy=+c.dataset.en;saveCheckin({energy:State.checkinEnergy});});
  const _ssCta=document.getElementById('ssCta');if(_ssCta)_ssCta.onclick=()=>{openPaywall();try{tg?.HapticFeedback?.impactOccurred('light');}catch(_){}};
  const _pwCta=document.getElementById('pwCta');if(_pwCta)_pwCta.onclick=()=>{
    // "💎 Tarifni tanlang" tugmasi — foydalanuvchini BOTGA olib boradi va
    // botda "💎 Premium → Obuna sotib olish" holati ochiladi. Ya'ni bot ichida
    // tariflar ro'yxati (payment method chooser'gacha yetmagan holat) chiqadi
    // va foydalanuvchi tarifini AYNAN BOT ICHIDA tanlaydi.
    //
    // NEGA specific plan tanlashdan voz kechildi: user tajribasi. Agar biz
    // avtomatik "featured" plan tanlab yuborsak, foydalanuvchi tanlash imkonini
    // yo'qotadi va bot darhol to'lov usulini so'raydi — bu chalkash. Endi CTA
    // bosilgach, botda odatiy Premium menyusi ochiladi va foydalanuvchi tarifni
    // BOT ichida ongli tanlaydi.
    try{tg?.HapticFeedback?.impactOccurred('medium');}catch(_){}
    // Bot deep-link: /start premium (plan_key bermayapmiz → bot Premium menyusi
    // ochiladi, tariflar ro'yxati bilan).
    try{
      const btn=_pwCta;
      const orig=btn.textContent;
      btn.disabled=true;
      btn.textContent='⏳ Botga o\'tkazilmoqda…';
      setTimeout(()=>{btn.disabled=false;btn.textContent=orig;},2500);
    }catch(_){}
    startCheckoutGeneric();
  };
  const _pwBack=document.getElementById('pwBack');if(_pwBack)_pwBack.onclick=()=>{closePaywall();try{tg?.HapticFeedback?.impactOccurred('light');}catch(_){}};
  document.getElementById('unlockOk').onclick=()=>document.getElementById('unlockOverlay').classList.remove('show');

  // ── Onboarding ─────────────────────────────────────────────────────
  // Onboarding faqat PREMIUM foydalanuvchiga (loadSubscription tasdiqlagach)
  // ko'rsatiladi — maybeShowOnboarding() orqali.
  document.querySelectorAll('#onboarding [data-go]').forEach(b=>b.onclick=()=>{const idx=+b.dataset.go;document.querySelectorAll('#onboarding .step').forEach(s=>s.classList.toggle('active',+s.dataset.step===idx));if(idx===3)renderObHabits();});
  document.querySelectorAll('#personaOpts .opt').forEach(o=>o.onclick=()=>{document.querySelectorAll('#personaOpts .opt').forEach(x=>x.classList.remove('sel'));o.classList.add('sel');localStorage.setItem('iz_persona',o.dataset.p);});
  const _commitOpt=document.getElementById('commitOpt');if(_commitOpt)_commitOpt.onclick=()=>_commitOpt.classList.toggle('sel');
  document.getElementById('obFinish').onclick=async()=>{
    const fin=document.getElementById('obFinish');if(fin)fin.disabled=true;
    const chosen=(State.obHabits||[]).filter(h=>h.sel);
    let added=0;
    for(const h of chosen){try{const nh=await apiHabitCreate({title:h.title,icon:h.icon,frequency:'daily',duration_type:'permanent'});State.habits.push(nh);added++;}catch(_){}}
    localStorage.setItem('iz_onboarded_v2','1');
    document.getElementById('onboarding').classList.remove('show');
    confetti(60);toast(added?('🚀 '+added+' ta odat qo\'shildi!'):'🚀 Boshlandi!');
    try{renderHabits();renderHabitSummary();}catch(_){}
    if(fin)fin.disabled=false;
  };
  const _shareCard=document.getElementById('shareCard');if(_shareCard)_shareCard.onclick=shareInvite;
  const _chBtn=document.getElementById('channelBtn');if(_chBtn)_chBtn.onclick=()=>openTgLink('https://t.me/Intizom_AI');
  const _adBtn=document.getElementById('adminBtn');if(_adBtn)_adBtn.onclick=()=>openTgLink('https://t.me/adxamovvvs');

  setTimeout(()=>{try{tg?.ready();}catch(_){}},100);
});
window.addEventListener('resize',moveGoalSegInd);
