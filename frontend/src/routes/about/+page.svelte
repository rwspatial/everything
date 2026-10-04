<script lang="ts">
	// About, services ("What I do") and contact ("Work with me") on one page; the landing page keeps the work.
	import { page } from '$app/state';
	import { site, title } from '$lib/site';

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
	<title>{title('About, services and contact')}</title>
</svelte:head>

<main class="about-page">
	<section
		class="banner"
		class:photo={!!site.hero.image}
		style:--hero-image={site.hero.image ? `url('${site.hero.image}')` : undefined}
		style:--hero-position={site.hero.position}
		aria-labelledby="about-title"
	>
		<div class="wrap">
			<h1 id="about-title">About {site.person || site.studio}</h1>
			<p class="role">{site.person ? `${site.role} · ${site.studio}` : 'Geospatial engineering & web mapping'} · {site.location}</p>
			<nav class="jump" aria-label="On this page">
				<a href="#services">What I do</a>
				<a href="#stack">How this site is built</a>
				<a href="#contact">Work with me</a>
			</nav>
		</div>
		{#if site.hero.image && site.hero.credit}
			<p class="credit">
				Photo: {#if site.hero.creditUrl}<a href={site.hero.creditUrl} rel="external noopener">{site.hero.credit}</a>{:else}{site.hero.credit}{/if}
			</p>
		{/if}
	</section>

	<section class="wrap block" aria-label="About">
		{#each site.about as para (para)}<p class="intro">{para}</p>{/each}
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

	<section id="stack" class="wrap block" aria-labelledby="stack-title">
		<h2 id="stack-title">How this site is built</h2>
		<ul class="stack" aria-label="Technology">
			{#each site.stack as t (t)}<li>{t}</li>{/each}
		</ul>
		<p class="small">
			Vector layers come from PostGIS views through an OGC API{#if !page.data.config?.publicMode}
				(<a href="/tiles/" rel="external">browse the Data API</a>){/if},
			rasters are Cloud-Optimized GeoTIFFs rendered on the fly, and a small API runs the imports, analysis jobs and PDF
			reports behind them. Maps are defined as validated JSON manifests, browser tests check every page, and the whole stack
			runs in Docker.
			<a href="/maps">See the live maps →</a>
		</p>
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
	.block { padding-top: 3rem; padding-bottom: 3rem; }
	h2 { font-size: 1.6rem; margin: 0 0 0.5rem; }
	.lede { color: var(--muted); margin: 0 0 1.5rem; max-width: 62ch; }
	.intro { max-width: 68ch; font-size: 1.1rem; margin: 0 0 1rem; }

	.banner { position: relative; overflow: hidden; background: #13202c; color: #fff; }
	/* The landing page's photo banner, shorter. */
	.banner.photo {
		background:
			linear-gradient(90deg, rgb(10 20 30 / 0.88) 0%, rgb(10 20 30 / 0.66) 45%, rgb(10 20 30 / 0.18) 100%),
			#13202c var(--hero-image) var(--hero-position, center) / cover no-repeat;
	}
	.banner .wrap { position: relative; padding-top: 3rem; padding-bottom: 2.5rem; }
	.banner h1 { font-size: clamp(1.9rem, 4vw, 2.6rem); line-height: 1.15; margin: 0; }
	.role { margin: 0.5rem 0 0; color: #a9c7da; }
	.jump { display: flex; flex-wrap: wrap; gap: 0.5rem 1.25rem; margin-top: 1.4rem; }
	.jump a { color: #5cc8e6; font-weight: 600; text-decoration: none; }
	.jump a:hover { text-decoration: underline; }
	.credit { position: absolute; right: 0.75rem; bottom: 0.4rem; margin: 0; font-size: 0.7rem; color: rgb(255 255 255 / 0.8); text-shadow: 0 1px 2px rgb(0 0 0 / 0.8); }
	.credit a { color: inherit; text-decoration: underline; }

	.band { background: var(--surface); border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); }
	.services { list-style: none; padding: 0; margin: 1.25rem 0 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 1.75rem; }
	.services h3 { margin: 0 0 0.35rem; font-size: 1.05rem; }
	.services p { margin: 0; color: var(--muted); font-size: 0.93rem; }

	.stack { list-style: none; padding: 0; margin: 0.8rem 0 1rem; display: flex; flex-wrap: wrap; gap: 0.4rem; }
	.stack li { font-size: 0.8rem; background: var(--surface); border: 1px solid var(--border); border-radius: 999px; padding: 0.15rem 0.65rem; }
	.small { font-size: 0.9rem; color: var(--muted); max-width: 70ch; }

	.dark { background: #13202c; color: #fff; border: 0; }
	.dark .lede { color: #a9c7da; }
	.contact { list-style: none; padding: 0; margin: 0; display: grid; gap: 0.6rem; }
	.contact li { display: flex; gap: 1rem; align-items: baseline; }
	.contact span { width: 6.5rem; color: #a9c7da; font-size: 0.85rem; }
	.contact a { color: #5cc8e6; font-weight: 600; }
	.todo { color: #f6d58e; }
	.todo code { color: #fff; }
</style>
