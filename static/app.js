'use strict';
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
let user, csrf = '', registering = false, entity = 'books', editing = null;
let cache = {}, records = [];
const labels = {books:'Книги',authors:'Авторы',branches:'Филиалы',copies:'Экземпляры',faculties:'Факультеты',catalog:'Каталог книг',loans:'Выдачи и возвраты',manage:'Управление фондом',reports:'Отчёты',audit:'Журнал действий'};
const fieldLabels = {id:'ID',title:'Название',name:'Название',author_id:'Автор',year:'Год издания',isbn:'ISBN / шифр',address:'Адрес',book_id:'Книга',branch_id:'Филиал',inventory_number:'Инвентарный номер'};
const schemas = {books:['title','author_id','year','isbn'],authors:['name'],branches:['name','address'],copies:['book_id','branch_id','inventory_number'],faculties:['name']};
const relations = {author_id:'authors',book_id:'books',branch_id:'branches'};
function el(tag, text, className) { const node = document.createElement(tag); if(text !== undefined) node.textContent = text; if(className) node.className = className; return node; }
function notice(message, failure=false) { const node=$('#notice'); node.textContent=message; node.hidden=false; node.classList.toggle('failure',failure); }
async function api(path, options={}) {
  const response = await fetch('/api'+path, {...options, headers:{'Content-Type':'application/json',...(csrf ? {'X-CSRF-Token':csrf}:{}),...options.headers}});
  const data = await response.json();
  if (!response.ok) {
    if(response.status===401 && !path.startsWith('/auth/')) { user=null; csrf=''; showAuth(); }
    throw new Error(data.error?.message || 'Не удалось выполнить запрос.');
  }
  return data;
}
function send(path, method, data) { return api(path,{method, ...(data===undefined?{}:{body:JSON.stringify(data)})}); }
async function perform(fn) { try { await fn(); } catch(error) { notice(error.message,true); } }
function fillSelect(select, items, placeholder) {
  select.replaceChildren();
  if(placeholder) { const o=el('option',placeholder); o.value=''; select.append(o); }
  items.forEach(item=>{const o=el('option',item.title||item.name||item.full_name);o.value=item.id;select.append(o);});
}
function table(headers, rows) {
  if(!rows.length) return el('div','Пока нет записей.','empty');
  const t=el('table'),thead=el('thead'),tr=el('tr'),tbody=el('tbody');
  headers.forEach(h=>tr.append(el('th',h)));thead.append(tr);t.append(thead,tbody);
  rows.forEach(row=>{const tr=el('tr');row.forEach(value=>{const td=el('td');value instanceof Node ? td.append(value) : td.textContent=value??'—';tr.append(td);});tbody.append(tr);});return t;
}
function button(text, handler, className) {const b=el('button',text,className);b.type='button';b.addEventListener('click',()=>perform(handler));return b;}
async function references() { const pairs=await Promise.all(['authors','branches','books','copies','faculties'].map(async key=>[key,(await api('/'+key)).items]));cache=Object.fromEntries(pairs); }
function showAuth() {$('#auth-screen').hidden=false;$('#app-screen').hidden=true;}
async function showApp() {
  $('#auth-screen').hidden=true;$('#app-screen').hidden=false;
  $('#account-name').textContent=user.full_name;$('#account-role').textContent=user.role==='librarian'?'Библиотекарь':'Читатель';
  $$('.staff').forEach(n=>n.hidden=user.role!=='librarian');
  await references();fillSelect($('#search-form [name=author_id]'),cache.authors,'Все авторы');fillSelect($('#search-form [name=branch_id]'),cache.branches,'Все филиалы');await page('catalog');
}
async function page(name) {
  $('#notice').hidden=true;
  $$('main > section').forEach(s=>s.hidden=s.id!=='page-'+name);
  $$('nav button').forEach(b=>b.classList.toggle('active',b.dataset.page===name));
  $('#page-title').textContent=labels[name];$('#breadcrumb').textContent=labels[name].toUpperCase();
  if(name==='catalog') await catalog();
  if(name==='loans') await loans();
  if(name==='manage') {await references();editing=null;await manage();}
  if(name==='reports') await reports();
  if(name==='audit') {const data=await api('/audit');const actions={post:'Добавление',put:'Изменение',delete:'Удаление',issue:'Выдача',return:'Возврат'};$('#audit-table').replaceChildren(table(['Дата UTC','Сотрудник','Действие','Раздел','ID'],data.items.map(r=>[r.created_at,r.actor,actions[r.action]||r.action,labels[r.entity]||r.entity,r.entity_id])));}
}
async function catalog() {
  const data=new FormData($('#search-form')),query=new URLSearchParams();
  for(const [key,value] of data) if(value) query.set(key,key==='available'?'true':value);
  const books=(await api('/books?'+query)).items,grid=$('#book-grid');grid.replaceChildren();$('#book-count').textContent='Найдено: '+books.length;
  if(!books.length) grid.append(el('div','Ничего не найдено. Попробуйте изменить условия поиска.','empty'));
  books.forEach(book=>{
    const card=el('article',undefined,'book-card'),cover=el('div',undefined,'book-cover'),info=el('div',undefined,'book-info');
    cover.append(el('div',book.title.charAt(0),'mini-book'));
    info.append(el('div',book.year+' · '+book.isbn,'book-meta'),el('h3',book.title),el('p',book.author,'muted'),el('span',book.available_copies?'Доступно '+book.available_copies+' из '+book.total_copies:'Нет свободных экземпляров','badge'+(book.available_copies?'':' busy')));
    card.append(cover,info);grid.append(card);
  });
}
async function loans() {
  if(user.role==='librarian') {
    await references();const copies=cache.copies.filter(c=>c.status==='available').map(c=>({id:c.id,title:c.inventory_number+' — '+c.title+' · '+c.branch}));
    fillSelect($('#issue-form [name=copy_id]'),copies,'Выберите экземпляр');fillSelect($('#issue-form [name=reader_id]'),(await api('/readers')).items,'Выберите читателя');
  }
  const rows=(await api('/loans')).items;
  $('#loan-list').replaceChildren(table(['Книга','Экземпляр','Читатель','Выдана','Срок возврата','Состояние','Действие'],rows.map(r=>[
    r.title,r.inventory_number,r.reader,r.issued_at,r.due_at,el('span',r.returned_at?'Возвращена '+r.returned_at:r.overdue?'Просрочена':'На руках','badge'+(r.overdue?' late':'')),
    !r.returned_at&&user.role==='librarian'?button('Принять возврат',async()=>{await send('/loans/'+r.id+'/return','POST',{});await loans();notice('Возврат принят. Экземпляр снова доступен.');}):'—'
  ])));
}
function entityForm() {
  const fields=$('#entity-fields');fields.replaceChildren();$('#edit-title').textContent=editing?'Изменить запись №'+editing:'Добавить запись';
  const current=records.find(r=>r.id===editing);
  schemas[entity].forEach(key=>{const label=el('label',entity==='authors'&&key==='name'?'Фамилия и имя':fieldLabels[key]);let input;
    if(relations[key]){input=el('select');fillSelect(input,cache[relations[key]],'Выберите…');}
    else {input=el('input');input.type=key==='year'?'number':'text';if(key==='year'){input.min=1450;input.max=2100;}else input.maxLength=['name','inventory_number','isbn'].includes(key)?120:200;}
    input.name=key;input.required=true;if(current)input.value=current[key];label.append(input);fields.append(label);
  });
}
async function manage() {
  records=(await api('/'+entity)).items;entityForm();
  const fields=schemas[entity];
  $('#entity-table').replaceChildren(table(['ID',...fields.map(k=>fieldLabels[k]),'Действия'],records.map(r=>{
    const actions=el('div');actions.append(button('Изменить',async()=>{editing=r.id;entityForm();$('#entity-form').scrollIntoView({behavior:'smooth'});}),button('Удалить',async()=>{
      if(!confirm('Удалить запись №'+r.id+'?'))return;
      await send('/'+entity+'/'+r.id,'DELETE');editing=null;await references();await manage();notice('Запись удалена.');
    },'danger'));
    return [r.id,...fields.map(k=>relations[k]?(cache[relations[k]].find(v=>v.id===r[k])?.title||cache[relations[k]].find(v=>v.id===r[k])?.name||r[k]):r[k]),actions];
  })));
}
async function reports() {
  const data=await api('/reports');$('#stats').replaceChildren();
  for(const [key,label] of [['books','Наименований книг'],['copies','Экземпляров в фонде'],['active_loans','Книг на руках'],['overdue','Просроченных выдач']]) {const box=el('div',undefined,'stat');box.append(el('span',label),el('strong',data[key]));$('#stats').append(box);}
  for(const [selector,items] of [['#popular',data.popular],['#faculty-report',data.faculties]]) {const target=$(selector);target.replaceChildren();if(!items.length)target.append(el('p','Нет данных.','muted'));items.forEach(r=>{const row=el('div',undefined,'report-row');row.append(el('span',r.title||r.name),el('strong',r.loan_count));target.append(row);});}
}
$('#toggle-auth').addEventListener('click',()=>{registering=!registering;$('#register-fields').hidden=!registering;$('#auth-title').textContent=registering?'Регистрация читателя':'Вход в библиотеку';$('#auth-submit').textContent=registering?'Создать аккаунт':'Войти';$('#toggle-auth').textContent=registering?'Уже есть аккаунт? Войти':'Нет аккаунта? Зарегистрироваться';$('#auth-hint').textContent=registering?'Создайте аккаунт для доступа к каталогу.':'Войдите, чтобы открыть каталог и посмотреть выдачи.';$('#auth-form [name=full_name]').required=registering;$('#auth-form [name=faculty_id]').required=registering;$('#auth-form [name=password]').minLength=registering?10:1;$('#auth-error').textContent='';});
$('#auth-form').addEventListener('submit',async event=>{event.preventDefault();$('#auth-error').textContent='';$('#auth-submit').disabled=true;try {
  const data=Object.fromEntries(new FormData(event.target));
  if(registering){data.faculty_id=Number(data.faculty_id);await send('/auth/register','POST',data);$('#toggle-auth').click();$('#auth-error').textContent='Аккаунт создан. Теперь войдите.';}
  else{const result=await send('/auth/login','POST',{username:data.username,password:data.password});user=result.user;csrf=result.csrf_token;event.target.reset();await showApp();}
}catch(error){$('#auth-error').textContent=error.message;}finally{$('#auth-submit').disabled=false;}});
$('#logout').addEventListener('click',()=>perform(async()=>{await send('/auth/logout','POST',{});user=null;csrf='';showAuth();}));
$$('nav button').forEach(b=>b.addEventListener('click',()=>perform(()=>page(b.dataset.page))));
$('#search-form').addEventListener('submit',e=>{e.preventDefault();perform(catalog);});
$('#issue-form').addEventListener('submit',e=>{e.preventDefault();perform(async()=>{const data=Object.fromEntries(new FormData(e.target));await send('/loans','POST',{copy_id:Number(data.copy_id),reader_id:Number(data.reader_id)});await loans();notice('Выдача оформлена.');});});
$$('#entity-tabs button').forEach(b=>b.addEventListener('click',()=>perform(async()=>{entity=b.dataset.entity;editing=null;$$('#entity-tabs button').forEach(x=>x.classList.toggle('active',x===b));await references();await manage();})));
$('#cancel-edit').addEventListener('click',()=>{editing=null;entityForm();});
$('#entity-form').addEventListener('submit',e=>{e.preventDefault();perform(async()=>{const data=Object.fromEntries(new FormData(e.target));for(const key of Object.keys(data))if(key.endsWith('_id')||key==='year')data[key]=Number(data[key]);await send('/'+entity+(editing?'/'+editing:''),editing?'PUT':'POST',data);editing=null;await references();await manage();notice('Запись сохранена.');});});
(async()=>{try{fillSelect($('#register-fields select'),(await api('/faculties/public')).items,'Выберите факультет');try{const data=await api('/auth/me');user=data.user;csrf=data.csrf_token;}catch(error){if(!error.message.includes('Требуется вход'))throw error;}if(user)await showApp();}catch(error){$('#auth-error').textContent='Не удалось загрузить приложение: '+error.message;}})();
