/** Project-specific claims must be approved before this site goes public. */
export const site = {
  name: process.env.NEXT_PUBLIC_SITE_NAME || "Your organization",
  tagline: process.env.NEXT_PUBLIC_SITE_TAGLINE || "An accessible place to learn about our services",
  description: process.env.NEXT_PUBLIC_SITE_DESCRIPTION || "Discover what we offer and how to contact us.",
  contactEmail: process.env.NEXT_PUBLIC_CONTACT_EMAIL || "",
  siteUrl: process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000",
} as const;

export const pages = [
  { href: "/", label: "Home" },
  { href: "/services", label: "Services" },
  { href: "/about", label: "About" },
  { href: "/resources", label: "Resources" },
  { href: "/blog", label: "Blog" },
  { href: "/contact", label: "Contact" },
] as const;
