"""The irregular verbs loaded into the `irregular_verbs` table at startup.

One verb per line: base, past (V2), participle (V3), then the Russian translation.
A slash keeps two accepted variants ("was/were"). Verbs already in the table are not changed.
"""

_TABLE = """
arise | arose | arisen | возникать
awake | awoke | awoken | просыпаться
be | was/were | been | быть
bear | bore | born | рождать, выносить
beat | beat | beaten | бить
become | became | become | становиться
begin | began | begun | начинать
bend | bent | bent | гнуть
bet | bet | bet | держать пари
bind | bound | bound | связывать
bite | bit | bitten | кусать
bleed | bled | bled | кровоточить
blow | blew | blown | дуть
break | broke | broken | ломать
breed | bred | bred | разводить
bring | brought | brought | приносить
broadcast | broadcast | broadcast | транслировать
build | built | built | строить
burn | burnt/burned | burnt/burned | гореть, жечь
burst | burst | burst | лопаться
buy | bought | bought | покупать
cast | cast | cast | бросать
catch | caught | caught | ловить
choose | chose | chosen | выбирать
cling | clung | clung | цепляться
come | came | come | приходить
cost | cost | cost | стоить
creep | crept | crept | ползти
cut | cut | cut | резать
deal | dealt | dealt | иметь дело
dig | dug | dug | копать
do | did | done | делать
draw | drew | drawn | рисовать, тянуть
dream | dreamt/dreamed | dreamt/dreamed | мечтать, видеть сны
drink | drank | drunk | пить
drive | drove | driven | водить машину
eat | ate | eaten | есть
fall | fell | fallen | падать
feed | fed | fed | кормить
feel | felt | felt | чувствовать
fight | fought | fought | драться, бороться
find | found | found | находить
flee | fled | fled | убегать, спасаться
fling | flung | flung | швырять
fly | flew | flown | летать
forbid | forbade | forbidden | запрещать
forecast | forecast | forecast | предсказывать
forget | forgot | forgotten | забывать
forgive | forgave | forgiven | прощать
freeze | froze | frozen | замерзать
get | got | got | получать
give | gave | given | давать
go | went | gone | идти
grind | ground | ground | молоть
grow | grew | grown | расти
hang | hung | hung | висеть, вешать
have | had | had | иметь
hear | heard | heard | слышать
hide | hid | hidden | прятать
hit | hit | hit | ударять
hold | held | held | держать
hurt | hurt | hurt | ранить, болеть
keep | kept | kept | хранить
kneel | knelt | knelt | вставать на колени
know | knew | known | знать
lay | laid | laid | класть
lead | led | led | вести
lean | leant/leaned | leant/leaned | наклоняться
leap | leapt/leaped | leapt/leaped | прыгать
learn | learnt/learned | learnt/learned | учить
leave | left | left | уходить, оставлять
lend | lent | lent | одалживать
let | let | let | позволять
lie | lay | lain | лежать
light | lit | lit | зажигать
lose | lost | lost | терять
make | made | made | делать
mean | meant | meant | значить
meet | met | met | встречать
mistake | mistook | mistaken | ошибаться
overcome | overcame | overcome | преодолевать
pay | paid | paid | платить
prove | proved | proven/proved | доказывать
put | put | put | класть
quit | quit | quit | бросать, уходить
read | read | read | читать
ride | rode | ridden | ездить верхом
ring | rang | rung | звонить
rise | rose | risen | подниматься
run | ran | run | бежать
saw | sawed | sawn | пилить
say | said | said | говорить, сказать
see | saw | seen | видеть
seek | sought | sought | искать
sell | sold | sold | продавать
send | sent | sent | отправлять
set | set | set | устанавливать
sew | sewed | sewn | шить
shake | shook | shaken | трясти
shine | shone | shone | светить
shoot | shot | shot | стрелять
show | showed | shown | показывать
shrink | shrank | shrunk | сжиматься
shut | shut | shut | закрывать
sing | sang | sung | петь
sink | sank | sunk | тонуть
sit | sat | sat | сидеть
sleep | slept | slept | спать
slide | slid | slid | скользить
smell | smelt/smelled | smelt/smelled | пахнуть, нюхать
speak | spoke | spoken | говорить
speed | sped | sped | мчаться
spell | spelt/spelled | spelt/spelled | писать по буквам
spend | spent | spent | тратить
spill | spilt/spilled | spilt/spilled | проливать
spin | spun | spun | крутить
spit | spat | spat | плевать
split | split | split | раскалывать
spoil | spoilt/spoiled | spoilt/spoiled | портить
spread | spread | spread | распространять
spring | sprang | sprung | прыгать
stand | stood | stood | стоять
steal | stole | stolen | красть
stick | stuck | stuck | приклеивать
sting | stung | stung | жалить
stink | stank | stunk | вонять
strike | struck | struck | ударять
swear | swore | sworn | клясться
sweep | swept | swept | подметать
swim | swam | swum | плавать
swing | swung | swung | качаться
take | took | taken | брать
teach | taught | taught | учить, обучать
tear | tore | torn | рвать
tell | told | told | рассказывать
think | thought | thought | думать
throw | threw | thrown | бросать
understand | understood | understood | понимать
upset | upset | upset | расстраивать
wake | woke | woken | будить, просыпаться
wear | wore | worn | носить одежду
weep | wept | wept | плакать
win | won | won | выигрывать
wind | wound | wound | заводить, наматывать
write | wrote | written | писать
"""

IRREGULAR_VERBS: tuple[tuple[str, str, str, str], ...] = tuple(
    tuple(part.strip() for part in line.split("|"))  # type: ignore[misc]
    for line in _TABLE.strip().splitlines()
)
