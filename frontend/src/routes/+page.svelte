<script lang="ts">
	import { site, title } from '$lib/site';

	let { data } = $props();
	const c = site.contact;
	const links = [
		c.email && { label: 'Email', text: c.email, href: `mailto:${c.email}` },
		c.phone && { label: 'Phone', text: c.phone, href: `tel:+1${c.phone.replace(/\D/g, '').replace(/^1(?=\d{10}$)/, '')}` },
		c.booking && { label: 'Book a call', text: 'Pick a time', href: c.booking },
		c.linkedin && { label: 'LinkedIn', text: c.linkedin.replace(/^https?:\/\/(www\.)?/, ''), href: c.linkedin },
		c.github && { label: 'GitHub', text: c.github.replace(/^https?:\/\/(www\.)?/, ''), href: c.github }
	].filter(Boolean) as { label: string; text: string; href: string }[];
</script>

<svelte:head>
	<title>{site.person ? title(`${site.person}, ${site.role}`) : title('Geospatial engineering & web mapping')}</title>
</svelte:head>

<main class="landing">
	<section class="hero" aria-labelledby="hero-title">
		<svg class="contours" viewBox="0 0 600 300" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
			{#each [0, 1, 2, 3, 4, 5, 6, 7] as i (i)}
				<path d="M-20 {60 + i * 30} C 120 {20 + i * 34}, 220 {110 + i * 26}, 340 {70 + i * 30} S 540 {30 + i * 32}, 640 {80 + i * 28}" />
			{/each}
		</svg>
		<div class="wrap">
			{#if site.person}
				<h1 id="hero-title">{site.person}</h1>
				<p class="role">{site.role} · <span>{site.studio}</span> · {site.location}</p>
			{:else}
				<h1 id="hero-title">{site.studio}</h1>
				<p class="role">Geospatial engineering &amp; web mapping · {site.location}</p>
			{/if}
			<p class="tagline">{site.tagline}</p>
			<div class="cta">
				<a class="btn primary" href="#work">See the work</a>
				<a class="btn" href="#contact">Get in touch</a>
			</div>
		</div>
	</section>

	<section id="work" class="wrap block" aria-labelledby="work-title">
		<h2 id="work-title">Selected work</h2>
		<p class="lede">Live maps of Maine, served from PostGIS on this site. Open one and click anything.</p>
		{#if data.featured.length}
			<ul class="work" aria-label="Selected work">
				{#each data.featured as p (p.slug)}
					<li>
						<a class="case" href="/p/{p.slug}">
							<span class="thumb" aria-hidden="true">{p.title.replace(/^Maine\s+/, '').slice(0, 1)}</span>
							<span class="case-body">
								<strong>{p.title}</strong>
								<span class="desc">{p.description}</span>
								<span class="meta">{p.layerCount} layers · Open map →</span>
							</span>
						</a>
					</li>
				{/each}
			</ul>
		{:else}
			<p class="lede">Project maps are loading or unavailable right now.</p>
		{/if}
		<p><a href="/maps">All {data.total || ''} map projects, including experiments →</a></p>
	</section>

	<section id="services" class="band" aria-labelledby="services-title">
		<div class="wrap block">
			<h2 id="services-title">What I do</h2>
			<ul class="services">
				{#each site.services as s (s.title)}
					<li><h3>{s.title}</h3><p>{s.body}</p></li>
				{/each}
			</ul>
		</div>
	</section>

	<section id="about" class="wrap block two" aria-labelledby="about-title">
		<div>
			<h2 id="about-title">About</h2>
			{#each site.about as para (para)}<p>{para}</p>{/each}
		</div>
		<div>
			<h3>How this site is built</h3>
			<ul class="stack" aria-label="Technology">
				{#each site.stack as t (t)}<li>{t}</li>{/each}
			</ul>
			<p class="small">
				Vector layers come from PostGIS views through an OGC API (<a href="/tiles/collections" rel="external">browse the data API</a>),
				rasters are Cloud-Optimized GeoTIFFs rendered on the fly, and the whole stack runs in Docker.
			</p>
		</div>
	</section>

	<section id="contact" class="band dark" aria-labelledby="contact-title">
		<div class="wrap block">
			<h2 id="contact-title">Work with me</h2>
			<p class="lede">Available for freelance projects and open to full-time geospatial roles.</p>
			{#if links.length}
				<ul class="contact">
					{#each links as l (l.label)}
						<li><span>{l.label}</span><a href={l.href} rel={l.href.startsWith('http') ? 'external noopener' : undefined}>{l.text}</a></li>
					{/each}
				</ul>
			{:else}
				<p class="todo">Contact details not set yet: add them to <code>frontend/src/lib/site.ts</code>.</p>
			{/if}
		</div>
	</section>
</main>

<style>
	.wrap { max-width: 1100px; margin: 0 auto; padding: 0 1.5rem; }
	.block { padding-top: 3.5rem; padding-bottom: 3.5rem; }
	h2 { font-size: 1.6rem; margin: 0 0 0.5rem; }
	.lede { color: var(--muted); margin: 0 0 1.5rem; max-width: 62ch; }

	.hero { position: relative; overflow: hidden; background: #13202c; color: #fff; }
	.hero .wrap { position: relative; padding-top: 5rem; padding-bottom: 5rem; }
	.contours { position: absolute; inset: 0; width: 100%; height: 100%; }
	.contours path { fill: none; stroke: #5cc8e6; stroke-opacity: 0.16; stroke-width: 1.2; }
	.hero h1 { font-size: clamp(2.2rem, 5vw, 3.4rem); line-height: 1.1; margin: 0; letter-spacing: -0.01em; }
	.role { margin: 0.6rem 0 0; color: #a9c7da; font-size: 1.05rem; }
	.role span { color: #5cc8e6; }
	.tagline { margin: 1.5rem 0 0; max-width: 52ch; font-size: 1.2rem; color: #e3edf4; }
	.cta { display: flex; flex-wrap: wrap; gap: 0.75rem; margin-top: 2rem; }
	.btn { display: inline-block; padding: 0.6rem 1.1rem; border-radius: 8px; font-weight: 600; text-decoration: none; border: 1px solid #5cc8e6; color: #fff; }
	.btn:hover { color: #fff; background: rgb(92 200 230 / 0.15); }
	.btn.primary { background: #5cc8e6; color: #0d1a24; }
	.btn.primary:hover { background: #82d7ee; color: #0d1a24; }

	.work { list-style: none; padding: 0; margin: 0 0 1.25rem; display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 1rem; }
	.case { display: flex; flex-direction: column; height: 100%; background: var(--surface); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; color: var(--text); text-decoration: none; transition: border-color 0.15s, transform 0.15s; }
	.case:hover { border-color: var(--accent); transform: translateY(-2px); color: var(--text); }
	.thumb {
		height: 96px; display: grid; place-items: center; font-size: 2rem; font-weight: 700; color: rgb(255 255 255 / 0.9);
		background-color: #0b6e8a;
		background-image: linear-gradient(rgb(255 255 255 / 0.12) 1px, transparent 1px), linear-gradient(90deg, rgb(255 255 255 / 0.12) 1px, transparent 1px);
		background-size: 22px 22px;
	}
	.case-body { display: flex; flex-direction: column; gap: 0.4rem; padding: 0.9rem 1rem 1rem; flex: 1; }
	.case-body strong { font-size: 1.05rem; }
	.desc { color: var(--muted); font-size: 0.88rem; }
	.meta { margin-top: auto; font-size: 0.82rem; font-weight: 600; color: var(--accent-strong); }

	.band { background: var(--surface); border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); }
	.services { list-style: none; padding: 0; margin: 1.25rem 0 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 1.75rem; }
	.services h3 { margin: 0 0 0.35rem; font-size: 1.05rem; }
	.services p { margin: 0; color: var(--muted); font-size: 0.93rem; }

	.two { display: grid; grid-template-columns: 1.3fr 1fr; gap: 3rem; }
	.two p { max-width: 62ch; }
	.two h3 { margin: 0.3rem 0 0.8rem; font-size: 1.05rem; }
	.stack { list-style: none; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: 0.4rem; }
	.stack li { font-size: 0.8rem; background: var(--surface); border: 1px solid var(--border); border-radius: 999px; padding: 0.15rem 0.65rem; }
	.small { font-size: 0.85rem; color: var(--muted); }

	.dark { background: #13202c; color: #fff; border: 0; }
	.dark .lede { color: #a9c7da; }
	.contact { list-style: none; padding: 0; margin: 0; display: grid; gap: 0.6rem; }
	.contact li { display: flex; gap: 1rem; align-items: baseline; }
	.contact span { width: 6.5rem; color: #a9c7da; font-size: 0.85rem; }
	.contact a { color: #5cc8e6; font-weight: 600; }
	.todo { color: #f6d58e; }
	.todo code { color: #fff; }

	@media (max-width: 760px) {
		.two { grid-template-columns: 1fr; gap: 1.5rem; }
		.hero .wrap { padding-top: 3.5rem; padding-bottom: 3.5rem; }
	}
	@media (prefers-reduced-motion: reduce) { .case { transition: none; } .case:hover { transform: none; } }
</style>
