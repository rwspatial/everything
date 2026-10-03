<script lang="ts">
	import { page } from '$app/state';
	import { site, title } from '$lib/site';

	let { data } = $props();
</script>

<svelte:head>
	<title>{site.person ? title(`${site.person}, ${site.role}`) : title('Geospatial engineering & web mapping')}</title>
</svelte:head>

<main class="landing">
	<section
		class="hero"
		class:photo={!!site.hero.image}
		style:--hero-image={site.hero.image ? `url('${site.hero.image}')` : undefined}
		style:--hero-position={site.hero.position}
		aria-labelledby="hero-title"
	>
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
				<a class="btn" href="/about#contact">Get in touch</a>
			</div>
		</div>
		{#if site.hero.image && site.hero.credit}
			<p class="credit">
				Photo: {#if site.hero.creditUrl}<a href={site.hero.creditUrl} rel="external noopener">{site.hero.credit}</a>{:else}{site.hero.credit}{/if}
			</p>
		{/if}
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
		<p><a href="/maps">{page.data.config?.publicMode ? `All ${data.total || ''} maps →` : `All ${data.total || ''} map projects, including experiments →`}</a></p>
	</section>

	<section class="band" aria-label="About, services and contact">
		<div class="wrap teaser">
			<p>Pipelines, spatial databases, tile services and web maps for Maine and beyond.</p>
			<a class="btn primary" href="/about">About, services and contact →</a>
		</div>
	</section>
</main>

<style>
	.wrap { max-width: 1100px; margin: 0 auto; padding: 0 1.5rem; }
	.block { padding-top: 3.5rem; padding-bottom: 3.5rem; }
	h2 { font-size: 1.6rem; margin: 0 0 0.5rem; }
	.lede { color: var(--muted); margin: 0 0 1.5rem; max-width: 62ch; }

	.hero { position: relative; overflow: hidden; background: #13202c; color: #fff; }
	/* Photo banner: darkened on the text side so the heading and buttons keep their contrast. */
	.hero.photo {
		background:
			linear-gradient(90deg, rgb(10 20 30 / 0.88) 0%, rgb(10 20 30 / 0.66) 45%, rgb(10 20 30 / 0.18) 100%),
			#13202c var(--hero-image) var(--hero-position, center) / cover no-repeat;
	}
	.hero .wrap { position: relative; padding-top: 5rem; padding-bottom: 5rem; }
	.credit { position: absolute; right: 0.75rem; bottom: 0.4rem; margin: 0; font-size: 0.7rem; color: rgb(255 255 255 / 0.8); text-shadow: 0 1px 2px rgb(0 0 0 / 0.8); }
	.credit a { color: inherit; text-decoration: underline; }
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

	.teaser { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 1rem; padding-top: 2rem; padding-bottom: 2rem; }
	.teaser p { margin: 0; font-size: 1.1rem; }
	.band { background: var(--surface); border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); }



	@media (max-width: 760px) {
			.hero .wrap { padding-top: 3.5rem; padding-bottom: 3.5rem; }
	}
	@media (prefers-reduced-motion: reduce) { .case { transition: none; } .case:hover { transform: none; } }
</style>
